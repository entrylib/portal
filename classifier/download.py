"""Run at image build: fetch the model and OpenAlex's topic list, and write the label table.

Writes to /opt/classifier:
  model/          the model files
  table.json      {model label: {topic, subfield}}
  about.json      {"classifier": "<model id>@<commit>", "topics_fetched": "<date>"}

Labels whose topic OpenAlex has retired are skipped and listed in about.json; the build fails if more
than 1% are, which means the mapping is wrong.

OpenAlex requires an API key (a free one is enough: openalex.org/settings/api). It is passed as a Docker build
secret, `openalex_api_key`, so it is never stored in the image; OPENALEX_API_KEY is read when run outside Docker.
"""

import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download
from labels import build_table

MODEL = os.environ.get("CLASSIFIER_MODEL",
                       "OpenAlex/bert-base-multilingual-cased-finetuned-openalex-topic-classification-title-abstract")
REVISION = os.environ.get("CLASSIFIER_MODEL_REVISION", "main")
OUT = Path(os.environ.get("CLASSIFIER_DIR", "/opt/classifier"))
SECRET = Path("/run/secrets/openalex_api_key")


#: Weights for other frameworks than PyTorch, which the server never loads: a model repository may hold the same weights
#: several times over (TensorFlow, Flax, ONNX), each as large as the model.
OTHER_WEIGHTS = ["*.h5", "*.msgpack", "*.onnx", "*.ot", "*.tflite", "*.mlmodel", "onnx/*", "coreml/*", "openvino/*",
                 "tf_model*", "flax_model*", "rust_model*"]


def ignored(files):
    """What not to fetch of a model repository's files: other frameworks' weights, and the PyTorch `.bin` copy when the
    same weights are there as safetensors (which transformers loads first)."""
    out = list(OTHER_WEIGHTS)
    if any(f.endswith(".safetensors") for f in files):
        out.append("*.bin")
    return out


def api_key():
    key = SECRET.read_text().strip() if SECRET.exists() else os.environ.get("OPENALEX_API_KEY", "").strip()
    if not key:
        raise SystemExit("an OpenAlex API key is needed to fetch the topic list: pass the build secret "
                         "openalex_api_key (or set OPENALEX_API_KEY); a free key is at openalex.org/settings/api")
    return key


def openalex_topics():
    topics, cursor, key = [], "*", api_key()
    while cursor:
        q = urllib.parse.urlencode({"per-page": 200, "cursor": cursor, "select": "id,display_name,subfield",
                                    "api_key": key})
        with urllib.request.urlopen(f"https://api.openalex.org/topics?{q}", timeout=60) as res:
            page = json.loads(res.read())
        topics += page["results"]
        cursor = page["meta"].get("next_cursor")
        time.sleep(0.2)
    return topics


def main():
    commit = HfApi().model_info(MODEL, revision=REVISION).sha     # pin the build to one commit of the model
    files = HfApi().list_repo_files(MODEL, revision=commit)
    snapshot_download(MODEL, revision=commit, local_dir=OUT / "model", ignore_patterns=ignored(files))
    config = json.loads((OUT / "model" / "config.json").read_text())
    labels = list(config["id2label"].values())
    topics = openalex_topics()
    table, retired = build_table(topics, labels)
    (OUT / "table.json").write_text(json.dumps(table, ensure_ascii=False))
    (OUT / "about.json").write_text(json.dumps({"classifier": f"{MODEL}@{commit}",
                                                "topics_fetched": dt.date.today().isoformat(),
                                                "labels": len(labels), "openalex_topics": len(topics),
                                                "retired_labels": retired}, ensure_ascii=False))
    print(f"{len(table)} of {len(labels)} labels mapped to current OpenAlex topics; {len(retired)} retired "
          f"topic(s) skipped: {retired}; model {MODEL}@{commit}")


if __name__ == "__main__":
    main()
