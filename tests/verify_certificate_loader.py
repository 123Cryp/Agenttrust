import importlib.util
import os

_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "verification", "verify_certificate.py")
_spec = importlib.util.spec_from_file_location("verify_certificate", _path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
verify = _mod.verify
canon = _mod.canon
sha = _mod.sha
module = _mod
