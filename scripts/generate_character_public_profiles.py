"""Build offline public cards from the worker's explicit presentation allowlist."""
import argparse
import json
from pathlib import Path
import sys

def generate(root:Path, path:Path):
    sys.path.insert(0,str(root))
    from services.character_ai.public_profiles import public_catalog
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(public_catalog(),ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=root/'.local/exports/CharacterPublicProfiles.json')
    generate(root, parser.parse_args().output)
