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
