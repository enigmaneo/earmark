import sys
import pathlib

p = pathlib.Path(sys.argv[1])
s = p.read_text()

s = s.replace(
    'data = numpy.fromstring(fid.read(size), dtype=dtype)',
    'data = numpy.frombuffer(fid.read(size), dtype=dtype)',
)

p.write_text(s)

for pyc in p.parent.glob('__pycache__/wavfile*.pyc'):
    pyc.unlink()
