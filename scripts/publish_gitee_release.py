"""Upload Gitee assets, sign dual-source metadata, then stage its public index.

Run before publish_release.py; commit/push updates/stable.json only after success.
The token and Ed25519 key stay in LOCALAPPDATA/IsaacLinkPublisher.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request
from cryptography.hazmat.primitives import serialization

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from isaac_link.updates import verified_manifest,verify_package,https_url


def main():
    publisher=Path(os.environ['LOCALAPPDATA'])/'IsaacLinkPublisher'
    p=argparse.ArgumentParser()
    p.add_argument('--folder',type=Path,required=True)
    p.add_argument('--token-file',type=Path,default=publisher/'gitee-token.txt')
    args=p.parse_args();folder=args.folder.resolve()
    if not args.token_file.is_file():raise SystemExit('Missing Gitee API token file; no release was changed.')
    token=args.token_file.read_text(encoding='utf-8-sig').strip()
    if not token or any(c in token for c in '\r\n"\\'):raise SystemExit('Invalid token file format')
    manifest=verified_manifest((folder/'update.json').read_bytes())
    version=manifest['version'];tag='v'+version
    client=folder/('Isaac-Link-client-'+tag+'.zip');server=folder/('Isaac-Link-server-'+tag+'.zip')
    verify_package(client,manifest)
    if not server.is_file():raise SystemExit('Server archive missing')
    key=serialization.load_pem_private_key((publisher/'release-ed25519.pem').read_bytes(),password=None)
    if key.public_key().public_bytes_raw().hex()!=(ROOT/'isaac_link/release_public_key.txt').read_text().strip():raise SystemExit('Signing key mismatch')
    api='https://gitee.com/api/v5'
    repo=api+'/repos/bbbyeah/isaac-link'
    def call(url,method='GET',data=None):
        query=urllib.parse.urlencode({'access_token':token})
        url+=('&' if '?' in url else '?')+query
        req=urllib.request.Request(url,method=method,data=None if data is None else json.dumps(data).encode(),headers={'User-Agent':'Isaac-Link-Publisher','Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=60) as response:return json.load(response)
        except Exception as e:raise RuntimeError('Gitee API request failed: '+str(getattr(e,'code',type(e).__name__))) from None
    call(api+'/user')
    releases=call(repo+'/releases?per_page=100')
    release=next((r for r in releases if r['tag_name']==tag),None)
    notes=(ROOT/'docs/releases'/(version+'.md')).read_text(encoding='utf-8')
    if release is None:
        release=call(repo+'/releases','POST',dict(tag_name=tag,name='Isaac-Link '+version,body=notes,target_commitish='main',prerelease=False))
    rid=release['id']
    def upload(path):
        # Token passed through stdin, never command arguments or printed URLs.
        config='\n'.join(['form = "access_token='+token+'"','form = "file=@'+path.as_posix()+'"'])+'\n'
        command=['curl.exe','--config','-','--silent','--show-error','--fail','--connect-timeout','20','--max-time','600',repo+f'/releases/{rid}/attach_files']
        result=subprocess.run(command,input=config,text=True,capture_output=True)
        if result.returncode:raise RuntimeError('Gitee upload failed: curl '+str(result.returncode))
        return json.loads(result.stdout)
    def assets():
        current=call(repo+f'/releases/{rid}')
        result=current.get('assets',[])
        if isinstance(result,dict):result=result.get('links',[])
        return result
    def ensure(path):
        existing=next((a for a in assets() if a.get('name')==path.name),None)
        if existing is None:
            print('Uploading to Gitee: '+path.name,flush=True);upload(path)
            existing=next((a for a in assets() if a.get('name')==path.name),None)
        if not existing:raise RuntimeError('Uploaded attachment not listed: '+path.name)
        url=https_url(existing.get('browser_download_url') or existing.get('url',''))
        # Public fetch is required: no login credentials may be needed by clients.
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Isaac-Link'}),timeout=30) as response:
            https_url(response.url)
            if path==client:
                temp=folder/'gitee-verify.partial'
                count=0
                with temp.open('wb') as out:
                    while True:
                        block=response.read(262144)
                        if not block:break
                        count+=len(block)
                        if count>manifest['size']:raise ValueError('Mirror package oversized')
                        out.write(block)
                verify_package(temp,manifest);temp.unlink()
            else:
                if response.read(path.stat().st_size+1)!=path.read_bytes():raise ValueError('Mirror attachment differs: '+path.name)
        return url
    mirror=ensure(client);ensure(server)
    manifest['urls']=[f'https://github.com/BBByeah/Isaac-Link/releases/download/{tag}/{client.name}',mirror]
    payload=json.dumps(manifest,ensure_ascii=False,separators=(',',':')).encode()
    wrapper=json.dumps(dict(payload=base64.b64encode(payload).decode(),signature=base64.b64encode(key.sign(payload)).decode())).encode()
    old=next((a for a in assets() if a.get('name')=='update.json'),None)
    if old:
        # Refuse changing an existing signed attachment under the same filename.
        with urllib.request.urlopen(old.get('browser_download_url') or old['url'],timeout=30) as r:previous=r.read(131073)
        if previous!=wrapper:raise RuntimeError('Existing Gitee update.json differs; refusing replacement')
    (folder/'update.json').write_bytes(wrapper)
    ensure(folder/'update.json')
    index=ROOT/'updates/stable.json';index.parent.mkdir(exist_ok=True);index.write_bytes(wrapper)
    print('Gitee attachments publicly verified. Signed dual-source index staged at updates/stable.json.')


if __name__=='__main__':main()
