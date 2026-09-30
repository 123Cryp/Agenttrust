import json

import verify_certificate_loader as vcl


def check_cert(chain, aid):
    cert = chain.view("get_certificate", aid)
    bundle = {"evidence": chain.view("get_evidence_bundle", aid), "challenges": chain.view("get_challenges", aid)}
    report = vcl.verify(cert, bundle, chain.view("get_certificate_hash", aid))
    assert report.valid(), report.text()
    return json.loads(cert)
