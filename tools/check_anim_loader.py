"""Execute the actual client rebase in Unicorn against normalized race assets."""
import struct,sys,json
from pathlib import Path
from project_paths import client_path
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import *
from patch_wow import Pe32
BASE=0x10000000; MODEL=0x20000000; ANIM=0x30000000; STACK=0x40000000; STOP=0x50000000
def u32(b,p):return struct.unpack_from('<I',b,p)[0]
def put(b,p,v):struct.pack_into('<I',b,p,v)
def pair(b,p):return struct.unpack_from('<II',b,p)
# Normalized runtime record layout, same as M2WalkLayout.hpp.
TRACKS=((0x2c,88,((16,12),(36,8),(56,12))),
 (0x48,40,((0,12),(20,2))), (0x58,20,((0,2),)),
 (0x60,60,((0,12),(20,16),(40,12))), (0xf0,40,((20,1),)),
 (0x100,36,((24,0),)), (0x110,100,((16,36),(48,36),(80,12))))
TOP=(8,20,28,36,44,52,60,72,80,88,96,104,112,120,128,136,144,152,216,224,232,240,248,256,264,272,280,288,296)
def normalize(data):
 b=bytearray(data[8:8+u32(data,4)])
 assert b[:4]==b'MD20'
 for h in (264,288,296):assert u32(b,h)==0,'Unsupported fixture structure'
 n,so=pair(b,28); seq=[tuple(struct.unpack_from('<HH',b,so+i*64))+(u32(b,so+i*64+12),struct.unpack_from('<H',b,so+i*64+62)[0]) for i in range(n)]
 cn,co=pair(b,272)
 for i in range(cn):
  old=bytes(b[co+i*116:co+(i+1)*116]);p=co+i*100
  b[p:p+100]=old[:4]+struct.pack('<f',0.7853982)+old[4:12]+old[12:96]
 descriptors=[];seen=set()
 for h,stride,tracks in TRACKS:
  count,off=pair(b,h)
  for i in range(count):
   for delta,width in tracks:
    t=off+i*stride+delta;glob=struct.unpack_from('<h',b,t+2)[0]
    for a,size in ((t+4,4),)+(((t+12,width),) if width else ()):
     slots,sp=pair(b,a)
     assert sp+slots*8<=len(b)
     for j in range(slots):
      d=sp+j*8
      if d in seen:continue
      seen.add(d);keys,ptr=pair(b,d)
      if glob>=0 or seq[j][2]&32:
       assert ptr+keys*size<=len(b),(h,j,keys,ptr)
       put(b,d+4,BASE+ptr if keys else 0)
      else:descriptors.append((j,d,keys,ptr,size,h))
     put(b,a+4,BASE+sp if slots else 0)
 for h in TOP:
  n,o=pair(b,h);put(b,h+4,BASE+o if n else 0)
 if u32(b,16)&8:
  n,o=pair(b,304);put(b,308,BASE+o if n else 0)
 return bytes(b),seq,descriptors

def machine(exe):
 pe=Pe32(bytearray(exe));u=Uc(UC_ARCH_X86,UC_MODE_32)
 u.mem_map(pe.image_base,0x1000000)
 u.mem_write(pe.image_base,exe[:pe.size_of_headers])
 for s in pe.sections():u.mem_write(pe.image_base+s.virtual_address,exe[s.raw_offset:s.raw_offset+s.raw_size])
 for base,size in ((BASE,0x8000000),(MODEL,0x1000),(ANIM,0x1000000),(STACK,0x10000),(STOP,0x1000)):u.mem_map(base,size)
 # Native failure logger is not part of this test; preserve its cdecl stack.
 def logger(u,a,size,data):
  sp=u.reg_read(UC_X86_REG_ESP);ret=u32(u.mem_read(sp,4),0)
  u.reg_write(UC_X86_REG_ESP,sp+4);u.reg_write(UC_X86_REG_EIP,ret)
 u.hook_add(UC_HOOK_CODE,logger,begin=0x5eeb70,end=0x5eeb70)
 return u

def run(u,b,slot,payload):
 u.mem_write(BASE,b);u.mem_write(ANIM,payload)
 model=bytearray(0x200);put(model,0x150,BASE);put(model,0x16c,len(b));u.mem_write(MODEL,bytes(model))
 putargs=struct.pack('<IIII',STOP,slot,ANIM,len(payload));sp=STACK+0x8000
 u.mem_write(sp,putargs)
 u.mem_write(0xaf59d8,struct.pack('<I',0xffffffff))
 for reg in (UC_X86_REG_EAX,UC_X86_REG_EBX,UC_X86_REG_EDX,UC_X86_REG_ESI,UC_X86_REG_EDI,UC_X86_REG_EBP):u.reg_write(reg,0)
 u.reg_write(UC_X86_REG_ESP,sp);u.reg_write(UC_X86_REG_ECX,MODEL)
 u.emu_start(0x83c6e0,STOP,count=2000000)
 assert u.reg_read(UC_X86_REG_EIP)==STOP,'Did not return'
 return u.reg_read(UC_X86_REG_EAX),bytes(u.mem_read(BASE,len(b)))

def main():
 u=machine(Path(sys.argv[1]).read_bytes());root=client_path()/'Data/Patch-ModernRaces-HD.MPQ/Character'
 totals={'models':0,'sequences':0,'descriptors':0,'zeroOffsets':0,'failures':[]}
 for p in sorted(root.glob('*/*/*.m2')):
  b,seq,ds=normalize(p.read_bytes());checked=0
  for slot,(aid,sub,flags,alias) in enumerate(seq):
   if flags&32:continue
   target=slot;visited=set()
   while seq[target][2]&64:
    assert target not in visited;visited.add(target);target=seq[target][3]
   a,s,f,_=seq[target]
   anim=p.with_name(f'{p.stem}{a:04}-{s:02}.anim')
   assert anim.exists(),(p.stem,slot,a,s)
   raw=anim.read_bytes();assert raw[:4]==b'AFM2';payload=raw[8:8+u32(raw,4)]
   selected=[v for v in ds if v[0]==slot]
   for _,d,k,ptr,size,h in selected:assert not k or ptr+k*size<=len(payload),(p.stem,slot,h,k,ptr,len(payload))
   ok,result=run(u,b,slot,payload)
   if not ok:
    totals['failures'].append([p.stem,slot,'native rejected']);break
   for _,d,k,ptr,size,h in selected:
    expect=ANIM+ptr if k else 0;got=u32(result,d+4)
    assert got==expect,(p.stem,slot,h,hex(got),hex(expect))
    totals['descriptors']+=1
    if k and ptr==0:totals['zeroOffsets']+=1
   totals['sequences']+=1;checked+=1
  totals['models']+=1;print(p.stem,checked,flush=True)
 print(json.dumps(totals,indent=2))
if __name__=='__main__':main()
