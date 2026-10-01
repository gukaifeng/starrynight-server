#!/usr/bin/env python3
"""Provision the small local Chinese similarity model before enabling it.

Run with the character-AI venv. No Alibaba request, user text or key is sent.
The cache is private runtime data and is not bundled in the iPhone app.
"""
import argparse
import hashlib
import json
from pathlib import Path
from fastembed import TextEmbedding
from huggingface_hub import snapshot_download

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--config',type=Path,default=root/'.local/character-ai/settings.json')
args=parser.parse_args()
config=json.loads(args.config.read_text())
cache=Path(config['data_dir'])/'models/reply-novelty'
lock=json.loads((root/'services/character_ai/novelty-model.lock.json').read_text())
snapshot=Path(snapshot_download(repo_id=lock['onnx_repository'],revision=lock['revision'],cache_dir=str(cache),allow_patterns=list(lock['files'])))
for name,expected in lock['files'].items():
    assert hashlib.sha256((snapshot/name).read_bytes()).hexdigest()==expected['sha256'],'Model checksum mismatch: '+name
model=TextEmbedding(lock['model'],specific_model_path=str(snapshot),local_files_only=True,threads=2)
vector=next(model.embed(['语义检查准备完成。']))
assert len(vector)==512
manifest=[]
for path in sorted(cache.rglob('*')):
    if path.is_file() and path.suffix in ('.onnx','.json','.txt'):
        manifest.append(dict(path=str(path.relative_to(cache)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size))
(cache/'verified-files.json').write_text(json.dumps(manifest,indent=2))
config['semantic_novelty']=True
args.config.write_text(json.dumps(config,indent=2));args.config.chmod(0o600)
print('Chinese BGE similarity model ready: 512 dimensions, local CPU, no paid calls. Redeploy the AI worker to activate.')
