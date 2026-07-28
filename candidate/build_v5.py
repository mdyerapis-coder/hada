import zipfile, os, hashlib

base = "/home/m_dyer_apis_gmail_com/hada/candidate/v5/HADA-M1-durable-orchestrator"
out = "/home/m_dyer_apis_gmail_com/hada/releases/v5/HADA-M1-gcp-candidate-v5.zip"
os.makedirs(os.path.dirname(out), exist_ok=True)

def sha256_file(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda: f.read(65536), b''): h.update(b)
    return h.hexdigest()

with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
    for root,dirs,files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in ('.git','__pycache__')]
        for fn in files:
            if fn.endswith('.pyc'): continue
            fp=os.path.join(root,fn)
            arc=os.path.relpath(fp, "/home/m_dyer_apis_gmail_com/hada/candidate/v5")
            z.write(fp, arc)

print("zip:", out, os.path.getsize(out), "bytes")
print("sha256:", sha256_file(out))
with zipfile.ZipFile(out) as z:
    names=z.namelist()
    print("entries:", len(names))
    for n in names:
        if 'compose.yaml' in n or 'Dockerfile' in n or 'supervisor.sh' in n or 'loki/config.yml' in n:
            print("  ", n)
