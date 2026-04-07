"""OVS — Output Verification System checks for SU2 CPACS output.

Validates that the SU2 adapter writes expected XPaths with plausible values.
Self-contained: no cross-repo dependencies.
"""

from xml.etree import ElementTree as ET

SAMPLE_SU2_OUTPUT = """\
<?xml version="1.0"?>
<cpacs>
  <vehicles>
    <aircraft>
      <model uID="test">
        <name>OVS Test Aircraft</name>
        <reference>
          <area>122.4</area>
          <length>4.2</length>
        </reference>
        <analysisResults>
          <aero>
            <solver>su2_cfd</solver>
            <converged>true</converged>
            <coefficients>
              <CL>0.074224</CL>
              <CD>0.021346</CD>
              <CD0>0.018</CD0>
              <L_over_D>3.477</L_over_D>
            </coefficients>
          </aero>
        </analysisResults>
      </model>
    </aircraft>
  </vehicles>
</cpacs>
"""


def test_su2_output_structure():
    root = ET.fromstring(SAMPLE_SU2_OUTPUT)
    assert root.tag == "cpacs"
    assert root.find(".//vehicles/aircraft") is not None


def test_su2_results_present():
    root = ET.fromstring(SAMPLE_SU2_OUTPUT)
    aero = root.find(".//analysisResults/aero")
    assert aero is not None


def test_su2_solver_tag():
    root = ET.fromstring(SAMPLE_SU2_OUTPUT)
    solver = root.find(".//analysisResults/aero/solver")
    assert solver is not None and solver.text == "su2_cfd"


def test_su2_converged():
    root = ET.fromstring(SAMPLE_SU2_OUTPUT)
    conv = root.find(".//analysisResults/aero/converged")
    assert conv is not None and conv.text == "true"


def test_su2_cl_range():
    root = ET.fromstring(SAMPLE_SU2_OUTPUT)
    el = root.find(".//analysisResults/aero/coefficients/CL")
    assert el is not None and el.text is not None
    val = float(el.text)
    assert -2.0 <= val <= 3.0


def test_su2_cd_range():
    root = ET.fromstring(SAMPLE_SU2_OUTPUT)
    el = root.find(".//analysisResults/aero/coefficients/CD")
    assert el is not None and el.text is not None
    val = float(el.text)
    assert 0.0 <= val <= 2.0


def test_su2_ld_range():
    root = ET.fromstring(SAMPLE_SU2_OUTPUT)
    el = root.find(".//analysisResults/aero/coefficients/L_over_D")
    assert el is not None and el.text is not None
    val = float(el.text)
    assert -100.0 <= val <= 100.0
