"""Inline Tauren talk tracks and reindex shadow batches against current sections."""
import json
import struct
import sys
from pathlib import Path
from project_paths import WORKSPACE as ROOT, SOURCE_ROOT, dbc_path, client_path
sys.path.insert(0, str(SOURCE_ROOT / 'src'))
from wxl_races.chunks import read_chunks
from wxl_races.appearance import array


def inline_talk(model, anim):
  chunks = read_chunks(model)
  b = bytearray(chunks[0].payload)
  original = bytes(b)
  payload = read_chunks(anim)[0].payload
  n, seqs = array(b, 0x1c, 64)
  slots = [i for i in range(n) if struct.unpack_from('<HH', b, seqs+i*64) in ((60,0),(208,0))]
  assert len(slots) == 2
  assert all(not struct.unpack_from('<I', b, seqs+i*64+12)[0]&0x20 for i in slots)
  b.extend(b'\0'*(-len(b)%16)); base = len(b); b.extend(payload)
  patched = {}
  def half(at, size):
    count, off = array(original, at, 8)
    for slot in slots:
      if slot >= count: continue
      d = off+slot*8
      keys, ptr = struct.unpack_from('<II', original, d)
      if not keys: continue
      assert ptr+keys*size <= len(payload), (at,slot,ptr,keys,size)
      new = base+ptr
      assert d not in patched or patched[d] == new
      struct.pack_into('<I', b, d+4, new); patched[d] = new
      assert b[new:new+keys*size] == payload[ptr:ptr+keys*size]
  def track(at, size):
    if struct.unpack_from('<h', original, at+2)[0] >= 0: return
    half(at+4,4); half(at+12,size)
  for header,stride,tracks in (
      (0x2c,88,((16,12),(36,8),(56,12))),
      (0xf0,40,((20,1),)), (0x48,40,((0,12),(20,2))),
      (0x58,20,((0,2),)), (0x60,60,((0,12),(20,8),(40,12))),
      (0x110,116,((12,36),(44,36),(76,12),(96,12)))):
    count,off = array(original,header,stride)
    for i in range(count):
      for delta,size in tracks:track(off+i*stride+delta,size)
  for header in (0x108,0x120,0x128):
    assert struct.unpack_from('<I',original,header)[0] == 0, 'Unhandled animated structure'
  count,off = array(original,0x100,36)
  for i in range(count):
    at=off+i*36
    if struct.unpack_from('<h',original,at+26)[0] == -1:half(at+28,4)
  for slot in slots:
    at=seqs+slot*64+12
    struct.pack_into('<I',b,at,struct.unpack_from('<I',original,at)[0]|0x20)
  return b'MD21'+struct.pack('<I',len(b))+b+model[8+len(original):], len(patched)


def shadows(old, current):
  n,o=array(old,28,48); nc,oc=array(current,28,48)
  lookup={}
  for i in range(n):lookup.setdefault(old[o+i*48+2:o+(i+1)*48],[]).append(i)
  mapping={}
  for i in range(nc):
    candidates=lookup[current[oc+i*48+2:oc+(i+1)*48]]
    assert len(candidates)==1
    mapping[candidates[0]]=i
  count,off=array(old,48,12); records=[]
  for i in range(count):
    record=bytearray(old[off+i*12:off+(i+1)*12]);sid=struct.unpack_from('<H',record,4)[0]
    assert sid<n
    if sid in mapping:
      struct.pack_into('<H',record,4,mapping[sid]);records.append(record)
  b=bytearray(current);b.extend(b'\0'*(-len(b)%16));pos=len(b);b.extend(b''.join(records))
  struct.pack_into('<II',b,48,len(records),pos)
  assert b[64:len(current)]==current[64:]
  assert all(struct.unpack_from('<H',r,4)[0]<nc for r in records)
  return bytes(b), {'before':count,'after':len(records)}


def main():
  client=client_path()
  prefix=Path('Data/Patch-ModernRaces-HD.MPQ')
  out=ROOT/'build/runtime-v2'; report={'models':{},'shadows':{},'runtimeVerified':False}
  for sex in ('Male','Female'):
    rel=Path('Character/Tauren')/sex
    stem='Tauren'+sex
    model=(client/prefix/rel/(stem+'.m2')).read_bytes()
    anim=(client/prefix/rel/(stem+'0060-00.anim')).read_bytes()
    result,count=inline_talk(model,anim)
    target=out/prefix/rel/(stem+'.m2');target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(result)
    report['models'][stem]=count
  for f in sorted((client/prefix/'Character').glob('*/*/*.skin')):
    rel=f.relative_to(client/prefix)
    old=(ROOT/'build/Patch-ModernRaces-HD.MPQ'/rel).read_bytes()
    result,stats=shadows(old,f.read_bytes())
    target=out/prefix/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(result)
    report['shadows'][str(rel)]=stats
  assert len(report['shadows'])==140
  (out/'report.json').write_text(json.dumps(report,indent=2))
  print('Prepared 2 talk models and 140 shadow profiles:',report['models'])

if __name__=='__main__': main()
