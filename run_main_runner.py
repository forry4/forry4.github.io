import runpy
rp = runpy.run_path(r'c:\Users\Forrest\forrestm_projects\Spender\main.py', run_name='__main__')
public = [k for k in rp.keys() if not k.startswith('_')]
print('public keys from run_path:', len(public))
print(public[:200])
