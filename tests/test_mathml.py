"""portal/mathml.py (moved from claimset.mathml): inline LaTeX as MathML, without a script."""

import unittest

from portal.mathml import to_mathml


def body(tex):
    out = to_mathml(tex)
    assert out is not None, tex
    return out.split("<semantics>", 1)[1].split("<annotation", 1)[0]


class TestMathML(unittest.TestCase):
    def test_scripts_and_greek(self):
        self.assertEqual(body(r"y_t = \alpha^2"), "<mrow><msub><mi>y</mi><mi>t</mi></msub><mo>=</mo>"
                                                 "<msup><mi>α</mi><mn>2</mn></msup></mrow>")
        self.assertIn('<mi mathvariant="normal">Φ</mi>', body(r"\Phi^{-1}(\tau)"))
        self.assertIn("<msubsup><mi>e</mi><mi>t</mi><mn>2</mn></msubsup>", body("e_t^2"))
        self.assertIn('<msup><mi>y</mi><mo>′</mo></msup>', body("y'"))

    def test_a_fraction_without_braces_takes_one_token_each(self):
        """\\tfrac12 is one half: an argument without braces is one token, and of a number its first digit."""
        half = "<mfrac><mn>1</mn><mn>2</mn></mfrac>"
        self.assertIn(half, body(r"\tfrac12"))
        self.assertIn(half + '<mrow><msup><mi mathvariant="normal">sech</mi><mn>2</mn></msup>',
                      body(r"-\tfrac12\operatorname{sech}^2(x)"))
        self.assertIn("<mfrac><mn>1</mn><mi>n</mi></mfrac>", body(r"\frac1n\sum_t y_t"))
        self.assertIn("<mfrac><mn>1</mn><mn>24</mn></mfrac>", body(r"\tfrac1{24}"))
        self.assertIn("<mfrac><mi>v</mi><mi>σ</mi></mfrac>", body(r"\frac v\sigma"))
        self.assertIn("<mfrac><mn>12</mn><mn>5</mn></mfrac>", body(r"\frac{12}{5}"))          # braces keep the number
        self.assertIn('<mfrac linethickness="0"><mi>n</mi><mn>2</mn></mfrac>', body(r"\binom n2"))
        self.assertIn("<msup><mi>x</mi><mn>10</mn></msup>", body("x^10"))                       # scripts as before

    def test_a_delimiter_of_a_chosen_size(self):
        big = 'fence="true" stretchy="true" symmetric="true" minsize="1.2em" maxsize="1.2em"'
        self.assertIn(f"<mo {big}>(</mo>", body(r"\big(\tfrac{x}{2}\big)"))
        self.assertIn(f"<mo {big}>)</mo>", body(r"\big(\tfrac{x}{2}\big)"))
        for name, size in (("Big", "1.8em"), ("bigg", "2.4em"), ("Bigg", "3em"), ("Bigl", "1.8em"), ("biggr", "2.4em")):
            self.assertIn(f'minsize="{size}" maxsize="{size}">[</mo>', body(rf"\{name}[ x"), name)
        self.assertIn('maxsize="1.8em">{</mo>', body(r"\Big\{ x \Big\}"))
        self.assertIn('maxsize="1.2em">|</mo>', body(r"\big| x \big|"))
        self.assertEqual(body(r"\big x"), "<mi>x</mi>")                    # no delimiter follows: nothing to size

    def test_a_function_stands_off_its_argument(self):
        gap = '<mspace width="0.1667em"></mspace>'
        self.assertIn(f"<mi>ln</mi><mo>\u2061</mo>{gap}</mrow><mi>y</mi>", body(r"\ln y"))
        self.assertIn(f"<mo>\u2061</mo>{gap}</mrow><mfrac>", body(r"\ln\frac{a}{b}"))
        self.assertIn(f"<mo>\u2061</mo>{gap}</mrow><mi>θ</mi>", body(r"\sin \theta"))
        self.assertIn(f"<mo>\u2061</mo>{gap}</mrow><mi>x</mi>", body(r"\operatorname{sech} x"))
        for tex in (r"\tanh(x)", r"\exp\left(x\right)", r"\ln|x|", r"\max_x", r"\operatorname{sech}^2\Big(x\Big)",
                    r"\log = 1", r"\sin \le 1"):
            self.assertNotIn(gap, body(tex), tex)                          # none before a bracket or an operator

    def test_fractions_roots_and_accents(self):
        self.assertIn("<mfrac><mi>T</mi><mrow><mi>T</mi><mo>−</mo><mi>k</mi></mrow></mfrac>", body(r"\frac{T}{T-k}"))
        self.assertIn("<msqrt><msub><mi>V</mi><mi>h</mi></msub></msqrt>", body(r"\sqrt{V_h}"))
        self.assertIn("<mroot><mi>x</mi><mn>3</mn></mroot>", body(r"\sqrt[3]{x}"))
        self.assertIn('<mover accent="true"><mi>σ</mi><mo stretchy="false">^</mo></mover>', body(r"\hat\sigma"))
        self.assertIn('linethickness="0"', body(r"\binom{n}{k}"))

    def test_big_operators_and_functions(self):
        out = body(r"\sum_{t=1}^{T} e_t")
        self.assertIn('<munderover><mo largeop="true" movablelimits="true">∑</mo>', out)
        self.assertIn("<msubsup><mo largeop=\"true\">∫</mo>", body(r"\int_0^1 f"))
        self.assertIn("<munder><mi>max</mi><mi>x</mi></munder><mo>\u2061</mo>", body(r"\max_x f(x)"))
        self.assertIn("<mi>log</mi><mo>\u2061</mo>", body(r"\log x"))

    def test_fonts_fences_and_matrices(self):
        self.assertIn("<mi>𝔼</mi>", body(r"\mathbb{E}[x]"))
        self.assertIn("<mi>𝐅</mi>", body(r"\mathbf{F}"))
        self.assertIn("<mi>ℝ</mi>", body(r"\mathbb{R}"))
        self.assertIn('<mo fence="true" stretchy="true">(</mo><mfrac>', body(r"\left(\frac{a}{b}\right)"))
        self.assertIn("<mtable><mtr><mtd><mn>1</mn></mtd><mtd><mn>2</mn></mtd></mtr>",
                      body(r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}"))
        self.assertIn('<mtable columnalign="left">', body(r"\begin{cases} 0 & x < 0 \\ 1 & \text{otherwise} \end{cases}"))
        self.assertIn("<mtext>otherwise</mtext>", body(r"\text{otherwise}"))
        out = body(r"\begin{aligned} y_t &= w v_{t-1} \\ v_t &= F v_{t-1} \end{aligned}")
        self.assertIn('<mtable columnalign="right left" columnspacing="0"><mtr><mtd><msub><mi>y</mi>', out)

    def test_what_it_cannot_read(self):
        for tex in (r"\foo{x}", "x^{2", r"\left( x", r"\begin{tikz} x \end{tikz}", "a & b", "", "x" * 3000,
                    "{" * 200 + "x" + "}" * 200):
            with self.subTest(tex[:20]):
                self.assertIsNone(to_mathml(tex))

    def test_escaped(self):
        out = to_mathml("<script>alert(1)</script> & \\text{<b>}")
        self.assertIsNone(out)                                  # a bare & is not maths
        out = to_mathml(r"\text{<b>x</b>} < y")
        self.assertNotIn("<b>", out)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", out)
        self.assertIn('<annotation encoding="application/x-tex">\\text{&lt;b&gt;x&lt;/b&gt;} &lt; y</annotation>', out)

    def test_display(self):
        self.assertTrue(to_mathml("x", display=True).startswith('<math display="block">'))




class TestLongFormulae(unittest.TestCase):
    def test_a_long_formula_scrolls_instead_of_widening_the_page(self):
        from portal import page
        css = page.stylesheet()
        self.assertIn('math[display="block"] { margin: 10px 0; max-width: 100%; overflow-x: auto;', css)
        self.assertIn("@media (max-width: 640px) { math { max-width: 100%; overflow-x: auto;", css)
        self.assertIn(".cs-brief li > span:last-child { min-width: 0; }", css)

if __name__ == "__main__":
    unittest.main()
