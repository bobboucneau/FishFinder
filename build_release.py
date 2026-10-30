#!/usr/bin/env python3
"""Build a FishFinder release without accidentally packaging local settings/secrets.

Only VERSION.json's explicit application-file list is included. --include adds a
new source file deliberately; it never recursively sweeps a working directory.
The output is suitable for the owner-build path, or can be signed for publication.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile
from release_tools import make_manifest
from release_manager import Store


def build(source,identifier,sequence,output,includes=()):
    # Validate the identifier with the same policy as the installer, without
    # creating a Store or modifying the installed device.
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',identifier):raise ValueError('Invalid release ID')
    if sequence<1:raise ValueError('Sequence must be positive')
    source=Path(source).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    metadata=json.loads((source/'VERSION.json').read_text())
    names=sorted(set(metadata['files'])|set(includes))
    forbidden={'settings.json','networks.json','network-session.json'}
    for name in names:
        relative=PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or name in forbidden or relative.suffix in ('.db','.pem','.key'):
            raise ValueError('Unsafe/private package filename: '+name)
        target=source/name
        if not target.is_file() or not target.resolve().is_relative_to(source):raise ValueError('Missing/outside source file: '+name)
    metadata['version']=identifier
    metadata['change']='Owner/developer build; see source history for changes'
    metadata['files']={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in names}
    stem='FishFinder-'+identifier
    archive=output/(stem+'.zip');manifest=output/(stem+'.manifest.json')
    if archive.exists() or manifest.exists():raise ValueError('Output already exists; use a new build ID')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name in names:z.write(source/name,stem+'/'+name)
        z.writestr(stem+'/VERSION.json',json.dumps(metadata,indent=2)+'\n')
    make_manifest(archive,identifier,sequence,manifest)
    return archive,manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path);parser.add_argument('--id',required=True)
    parser.add_argument('--sequence',required=True,type=int);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--include',action='append',default=[])
    parser.add_argument('--private-key',type=Path,help='Optionally sign with your encrypted Ed25519 private key')
    args=parser.parse_args()
    try:
        archive,manifest=build(args.source,args.id,args.sequence,args.output,args.include)
        print('Package:',archive);print('Manifest:',manifest)
        if args.private_key:
            subprocess.run([sys.executable,str(Path(__file__).with_name('release_tools.py')),'sign',str(manifest),
                            '--private',str(args.private_key),'--output',str(archive.with_suffix('.sig'))],check=True)
        else:print('Unsigned owner build: staging requires --owner-build.')
    except (OSError,ValueError,KeyError) as exc:parser.exit(1,str(exc)+'\n')


if __name__=='__main__':main()
