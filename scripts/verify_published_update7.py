"""Verify the real public update source, download and frozen install lifecycle."""
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from isaac_link.updates import UpdateManager,SOURCES
from scripts.verify_frozen7 import main as verify_install

def main():
    manager=UpdateManager(ROOT/'ui-validation/published-download')
    manager.check();assert manager.status=='latest' and manager.manifest['version']=='0.7.0'
    print('PASS: public latest endpoint and signed manifest; 0.7.0 is current.',flush=True)
    with patch('isaac_link.updates.__version__','0.6.9'):
        manager.check();assert manager.status=='available'
    print('PASS: newer version detected for synthetic older client; downloading public artifact.',flush=True)
    manager.download();assert manager.status=='ready' and manager.progress==100
    print('PASS: public ZIP downloaded and signature verified.',flush=True)
    verify_install(manager.archive,manager.folder/'update.json','published-frozen-update.json')
    report=dict(result='PASS',source=SOURCES[0],version=manager.manifest['version'],
                current_client='latest',synthetic_older_client='available',download='100%',signature_verified=True,frozen_install_and_restart=True,
                scope='Actual GitHub latest endpoint and public asset; older-version marker is synthetic; not a 0.6.5 in-app migration')
    (ROOT/'ui-validation/published-update.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))

if __name__=='__main__':main()
