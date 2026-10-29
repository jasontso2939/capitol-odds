"""The outlook page scores "what the bill does" in the browser. Its textScore function must give
the same number as the fitted scikit-learn model (calleg.predict.TEXT settings) it was exported from."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from calleg import predict

ROOT = Path(__file__).resolve().parents[1]

TEXTS = [
    "An act to amend Section 1 of the Education Code, relating to school meals. Existing law requires school districts to provide meals.",
    "Housing: accessory dwelling units. This bill would require a local agency to approve accessory dwelling units ministerially.",
    "Wildfire prevention: vegetation management. The bill would appropriate funds to the Department of Forestry and Fire Protection.",
    "Taxation: income tax credit for child care. This bill would allow a credit against the personal income tax.",
    "Public health: vaccines. Existing law requires the State Department of Public Health to maintain an immunization registry.",
    "Elections: vote by mail ballots. This bill would require county elections officials to mail ballots to every registered voter.",
    "School meals: free breakfast. The bill would require school districts to provide a free breakfast to every pupil.",
    "Housing: density bonus. This bill would require a city to grant a density bonus for housing developments near transit.",
    "Fire protection: defensible space. This bill would require inspections of defensible space around homes in fire hazard zones.",
    "Child care: subsidized child care rates. The bill would appropriate funds to increase reimbursement rates for child care providers.",
] * 3
LABELS = [1, 0, 1, 0, 1, 0, 1, 1, 0, 0] * 3
QUERIES = [
    "Housing: accessory dwelling units near transit",
    "school meals and free breakfast for every pupil; school districts school districts",
    "wildfire vegetation management funds",
    "Zzz unrelated words only",
    "",
]


def browser_text_score() -> str:
    html = (ROOT / "site/index.html").read_text()
    m = re.search(r"function textScore\(str\) \{.*?\n\}", html, re.S)
    assert m, "textScore not found in site/index.html"
    return m.group(0)


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_browser_text_score_matches_sklearn(tmp_path):
    vec = TfidfVectorizer(**{**predict.TEXT, "min_df": 1}).fit(TEXTS)
    clf = LogisticRegression(C=predict.TEXT_C, max_iter=3000).fit(vec.transform(TEXTS), LABELS)
    typical = -9.0
    export = {"vocab": list(vec.get_feature_names_out()), "idf": [round(float(x), 4) for x in vec.idf_],
              "coef": [round(float(x), 4) for x in clf.coef_[0]], "intercept": round(float(clf.intercept_[0]), 4)}
    js = (f"const TXT = {json.dumps(export)}; const TIX = Object.fromEntries(TXT.vocab.map((w, i) => [w, i]));\n"
          f"const TYPICAL = {typical};\n{browser_text_score()}\n"
          f"console.log(JSON.stringify({json.dumps(QUERIES)}.map(textScore)));")
    (tmp_path / "t.js").write_text(js)
    got = json.loads(subprocess.run(["node", str(tmp_path / "t.js")], capture_output=True, text=True, check=True).stdout)
    want = clf.decision_function(vec.transform(QUERIES))
    want[-1] = typical   # nothing typed: the page uses the typical score
    assert np.allclose(got, want, atol=1e-3), (got, list(want))
