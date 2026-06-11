p = r'c:\Users\Forrest\forrestm_projects\Spender\main.py'
with open(p, 'rb') as f:
    b = f.read()
print('len bytes', len(b))
print('first 400 bytes repr:\n')
print(repr(b[:400]))
print('\ncontains NUL?', b.find(b'\x00')!=-1)
