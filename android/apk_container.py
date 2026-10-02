"""Select the DEX defining MainActivity; preserve all other upstream APK entries."""
import pathlib
import struct
import sys
import zipfile

def defines(data, descriptor):
    u32 = lambda off: struct.unpack_from('<I', data, off)[0]
    strings, types = u32(60), u32(68)
    count, offset = u32(96), u32(100)
    for index in range(count):
        type_id = u32(offset + index * 32)
        string_id = u32(types + type_id * 4)
        start = u32(strings + string_id * 4)
        # Skip ULEB128 UTF-16 length prefix.
        while data[start] & 128: start += 1
        start += 1
        end = data.index(b'\0', start)
        if data[start:end] == descriptor: return True
    return False

if sys.argv[1] == 'extract':
    with zipfile.ZipFile('/tmp/upstream.apk') as original:
        dex = [name for name in original.namelist() if name.startswith('classes') and name.endswith('.dex')]
        selected = [name for name in dex if defines(original.read(name), b'Lcom/lagradost/cloudstream3/MainActivity;')]
        if len(selected) != 1: raise SystemExit('Expected one MainActivity DEX definition')
        pathlib.Path('/tmp/main-dex-name').write_text(selected[0])
        with zipfile.ZipFile('/tmp/main.apk', 'w') as subset:
            subset.writestr('AndroidManifest.xml', original.read('AndroidManifest.xml'))
            subset.writestr('classes.dex', original.read(selected[0]))
elif sys.argv[1] == 'assemble':
    selected = pathlib.Path('/tmp/main-dex-name').read_text()
    with zipfile.ZipFile('/tmp/upstream.apk') as original, zipfile.ZipFile('/tmp/main-patched.apk') as patched, zipfile.ZipFile('/tmp/server-unsigned.apk','w',zipfile.ZIP_DEFLATED) as output:
        dex = [name for name in original.namelist() if name.startswith('classes') and name.endswith('.dex')]
        extra = 'classes' + str(len(dex) + 1) + '.dex'
        for entry in original.infolist():
            if entry.filename == selected:
                output.writestr(entry, patched.read('classes.dex'))
            elif entry.filename == 'META-INF/MANIFEST.MF' or (entry.filename.startswith('META-INF/') and entry.filename.rsplit('.',1)[-1].upper() in {'SF','RSA','DSA','EC'}):
                continue
            else: output.writestr(entry, original.read(entry.filename))
        output.write('/tmp/bridge/classes.dex', extra)
else:
    raise SystemExit('Use extract or assemble')
