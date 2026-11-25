import os,json,sys
from pathlib import Path
import nbformat
from nbclient import NotebookClient
root=Path.cwd()
k=root/'.cache/jupyter/kernels/mmip'
k.mkdir(parents=True,exist_ok=True)
(k/'kernel.json').write_text(json.dumps(dict(argv=[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}'],display_name='MMIP (Python 3.13.13)',language='python')),encoding='utf-8')
os.environ['JUPYTER_PATH']=str(root/'.cache/jupyter')
os.environ['PYTHONUTF8']='1'
nb=nbformat.read('main.ipynb',as_version=4)
client=NotebookClient(nb,timeout=900,kernel_name='mmip',resources={'metadata':{'path':str(root)}})
try:
 client.execute()
finally:
 nbformat.write(nb,'main.ipynb')
print('Notebook executed with',sys.executable)
