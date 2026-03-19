from glob import glob
import numpy as np
import polars as pl

name = []
category = []
filedir = []

for f in glob('*/*/*.kicad_sym')+glob('*/*/*/*.kicad_sym'):
    d = f.split('/')
    if 'tests' not in d:
        name.append((d[-1]).split('.')[0])
        category.append(d[0])
        filedir.append('/'.join(d[:-1]))
        #print(d)

components = pl.DataFrame({'name': name, 'category': category, 'directory': filedir, 'description': list(np.full_like(np.asarray(name), ''))}).unique().sort('name')

components.write_csv('list_of_components.csv')

print(components)

print('DONE')
