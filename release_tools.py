#!/usr/bin/env python3
"""Owner/developer commands: package, sign, stage, defer and roll back FishFinder.

Run --help first. No command installs Linux packages or needs sudo. A signing
private key is encrypted with a passphrase and must stay outside the repository.
An owner build is intentionally distinguished from an authenticated official one.
"""
import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import shutil
import zipfile
from release_manager import Store, atomic, sha256


def make_manifest(archive,identifier,sequence,output,platform='linux'):
    with zipfile.ZipFile(archive) as z:
        roots={name.split('/')[0] for name in z.namelist()}
        if len(roots)!=1:raise ValueError('Package must have one top-level directory')
    data=dict(schema=1,product='FishFinder',release_id=identifier,sequence=sequence,
              bootstrap_api=1,python_min=[3,10],platform=platform,folder=roots.pop(),
              size=Path(archive).stat().st_size,sha256=sha256(archive))
    atomic(output,data)
    return data


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home',type=Path,default=Path.home()/'.local/share/FishFinder')
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('manifest');p.add_argument('archive',type=Path);p.add_argument('--id',required=True);p.add_argument('--sequence',required=True,type=int);p.add_argument('--output',required=True,type=Path)
    p=sub.add_parser('keygen');p.add_argument('--private',required=True,type=Path);p.add_argument('--public',required=True,type=Path)
    p=sub.add_parser('sign');p.add_argument('manifest',type=Path);p.add_argument('--private',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p=sub.add_parser('trust-key');p.add_argument('public',type=Path);p.add_argument('--owner-authorized',action='store_true',required=True)
    p=sub.add_parser('stage');p.add_argument('archive',type=Path);p.add_argument('--manifest',required=True,type=Path);p.add_argument('--signature',type=Path);p.add_argument('--owner-build',action='store_true')
    p=sub.add_parser('defer');p.add_argument('policy',choices=('ask','next-start','later'))
    sub.add_parser('status');sub.add_parser('rollback')
    args=parser.parse_args()
    try:
        if args.action=='manifest':
            make_manifest(args.archive,args.id,args.sequence,args.output);print('Manifest written:',args.output);return
        if args.action=='keygen':
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives import serialization
            if args.private.exists() or args.public.exists():raise ValueError('Refusing to overwrite a key')
            phrase=getpass.getpass('New signing-key passphrase: ')
            if len(phrase)<12 or phrase!=getpass.getpass('Repeat passphrase: '):raise ValueError('Use matching passphrases of at least 12 characters')
            key=Ed25519PrivateKey.generate()
            args.private.parent.mkdir(parents=True,exist_ok=True);args.public.parent.mkdir(parents=True,exist_ok=True)
            with args.private.open('xb') as stream:
                os.chmod(args.private,0o600)
                stream.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.BestAvailableEncryption(phrase.encode())))
            args.public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo))
            print('Encrypted private key and public key created. Back up the private key securely; do not commit it.');return
        if args.action=='sign':
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            key=serialization.load_pem_private_key(args.private.read_bytes(),getpass.getpass('Signing-key passphrase: ').encode())
            if not isinstance(key,Ed25519PrivateKey):raise ValueError('Expected an Ed25519 key')
            args.output.write_bytes(base64.b64encode(key.sign(args.manifest.read_bytes())))
            print('Detached signature written:',args.output);return
        store=Store(args.home)
        if args.action=='trust-key':
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            key=serialization.load_pem_public_key(args.public.read_bytes())
            if not isinstance(key,Ed25519PublicKey):raise ValueError('Expected an Ed25519 public key')
            fingerprint=sha256(args.public)
            shutil.copyfile(args.public,store.home/'trusted-keys'/(fingerprint+'.pem'))
            print('Owner-authorized trust key:',fingerprint)
        elif args.action=='stage':
            print(json.dumps(store.stage(args.archive,args.manifest,args.signature,args.owner_build),indent=2))
            if args.owner_build:print('OWNER BUILD: checksummed but not authenticated as an official FishFinder release.')
            print('Running launcher will ask for approval; otherwise next startup will ask.')
        elif args.action=='defer':store.defer(args.policy);print('Pending update policy:',args.policy)
        elif args.action=='status':print(json.dumps(dict(state=store.state(),pending=__import__('release_manager').read(store.pending_path,None)),indent=2))
        elif args.action=='rollback':
            if not store.state().get('previous'):raise ValueError('No previous release to restore')
            # Request a supervisor restart rather than switching files underneath
            # running processes. The next supervisor startup performs the rollback.
            atomic(store.home/'runtime/rollback-request.json',{'requested':True})
            print('Rollback requested. Running launcher will restart into the retained previous version.')
    except (ValueError,OSError,KeyError,zipfile.BadZipFile) as exc:parser.exit(1,str(exc)+'\n')


if __name__=='__main__':main()
