import sys
import pathlib

p = pathlib.Path(sys.argv[1])
s = p.read_text()

s = s.replace(
    'from numpy import get_include\n    from numpy.distutils import misc_util',
    'from numpy import get_include as numpy_get_include',
)
s = ''.join(l for l in s.splitlines(keepends=True)
            if 'from numpy.distutils import misc_util' not in l)
s = s.replace('INCLUDE_DIRS = [misc_util.get_numpy_include_dirs()]',
              'INCLUDE_DIRS = [[numpy_get_include()]]')
s = s.replace('get_include()', 'numpy_get_include()')
s = s.replace('numpy_numpy_get_include()', 'numpy_get_include()')

p.write_text(s)
