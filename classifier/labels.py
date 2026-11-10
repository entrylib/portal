"""Mapping the model's labels to OpenAlex topics and subfields. Pure functions: no model, no network.

The model's labels look like "2543: Mapping Groundwater Potential Zones Using GIS Techniques". The number n is the
topic's ID less 10000: label 2543 is topic T12543. Topics are matched by that ID, not by name: OpenAlex has renamed
most topics since the model was trained (T12543 is now "Groundwater and Watershed Analysis"), while the IDs, and
the clusters they name, stayed. Each topic belongs to exactly one subfield.
"""

import re

_LABEL = re.compile(r"^\s*\d+\s*:\s*(.+?)\s*$")


def label_name(label):
    m = _LABEL.match(label)
    return m.group(1) if m else label.strip()


def short_id(openalex_id):
    """https://openalex.org/T10001 -> openalex:T10001; https://openalex.org/subfields/1803 -> openalex:subfields/1803"""
    return "openalex:" + openalex_id.rsplit("openalex.org/", 1)[-1]


def label_number(label):
    m = re.match(r"^\s*(\d+)\s*:", label)
    if not m:
        raise ValueError(f"model label without a number: {label!r}")
    return int(m.group(1))


def topic_id_of(label):
    """The OpenAlex topic ID a model label names: label n is T(10000 + n)."""
    return f"T{10000 + label_number(label)}"


#: At most this share of the model's labels may name topics OpenAlex has since retired; more means the mapping is
#: wrong, and the build fails.
MAX_RETIRED_SHARE = 0.01


def build_table(topics, labels):
    """({model label: {"topic", "subfield"}}, [retired labels]) from OpenAlex topic records ({id, display_name,
    subfield: {id}}) and the model's labels. A label whose topic OpenAlex no longer has is left out of the table,
    and the classifier skips it. Raises ValueError when more than MAX_RETIRED_SHARE of the labels are left out."""
    by_id = {t["id"].rsplit("/", 1)[-1]: t for t in topics}
    table, retired = {}, []
    for label in labels:
        topic = by_id.get(topic_id_of(label))
        if topic is None:
            retired.append(label)
        else:
            table[label] = {"topic": short_id(topic["id"]), "subfield": short_id(topic["subfield"]["id"])}
    if len(retired) > MAX_RETIRED_SHARE * len(labels):
        raise ValueError(f"{len(retired)} of {len(labels)} label(s) name a topic OpenAlex does not have, "
                         f"e.g. {retired[:3]}: the label-to-topic mapping is wrong")
    return table, retired


def classify(scored, table, max_topics=3):
    """{subfield, topics} from the model's [(label, score)], best first: up to three current topics, and the subfield
    with the most weight among all the topics scored (the sum of their scores), not merely the best topic's. A paper
    on forecasting intervals whose best topic is in Finance but whose next ones are in statistics and operations
    research is put in the subfield those share. Ties go to the subfield of the better topic."""
    known = [(label, score) for label, score in scored if label in table]   # skip topics OpenAlex has retired
    if not known:
        raise ValueError("the model returned no label of a current OpenAlex topic")
    weight, first = {}, {}
    for i, (label, score) in enumerate(known):
        sub = table[label]["subfield"]
        weight[sub] = weight.get(sub, 0.0) + float(score)
        first.setdefault(sub, i)
    subfield = max(weight, key=lambda s: (weight[s], -first[s]))
    return {"subfield": subfield, "topics": [table[label]["topic"] for label, _ in known[:max_topics]]}


def model_input(title, abstract):
    """The model's input format: "<TITLE> {title}\\n<ABSTRACT> {abstract}", NONE for a missing part."""
    return f"<TITLE> {title.strip() or 'NONE'}\n<ABSTRACT> {abstract.strip() or 'NONE'}"
