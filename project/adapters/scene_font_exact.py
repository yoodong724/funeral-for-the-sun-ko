"""Fail-closed full scene comparison allowing approved text and font additions.

Only append-only font names/variants and direct font node-property changes are
normalized. Unexplained changes are unsupported, never authorization.
"""
import struct
from project.adapters import full_scene_verify as scene, scene_font_s1 as font, scene_node_localize as node, rsrc_inspect as rs


def _nodes(bundle):
    out=[];words=bundle['nodes'];pos=0
    for item in bundle['state_nodes']:
        head=tuple(words[pos:pos+5]);count=words[pos+5];pos+=6
        props=[]
        for _ in range(count):props.append(tuple(words[pos:pos+2]));pos+=2
        ng=words[pos];pos+=1;groups=tuple(words[pos:pos+ng]);pos+=ng
        out.append((item['path'],head,props,groups))
    if pos!=len(words):raise scene.UnsupportedScene('장면 노드 배열 잔여')
    return out


def _bundle_items(value):
    if value.tag!=26 or len(value.children)%2:raise scene.UnsupportedScene('장면 딕셔너리 미지원')
    result=[]
    for i in range(0,len(value.children),2):
        kstep,k=value.children[i];vstep,v=value.children[i+1]
        if k.tag!=5 or kstep!=('dict_key',i//2) or vstep!=('dict_value',i//2):raise scene.UnsupportedScene('장면 딕셔너리 순서 미지원')
        result.append((k,v))
    return result


def verify(original,candidate,changes):
    """Return passed only for completely compared S1 + approved text changes."""
    scene._changes(changes)
    old,root,key,ov,ob=scene._bundle(original)
    new,newroot,newkey,nv,nb=scene._bundle(candidate)
    if root!=newroot or key!=newkey:raise scene.UnsupportedScene('장면 내부 구조 불일치')
    permitted={(x['node_path'],p) for x in changes for p in font.FONT_PROPERTIES}
    s1=font.verify_font_additions(original,candidate,approved_nodes=permitted)
    if s1.get('status')!='passed':raise scene.UnsupportedScene('글꼴 외부표 또는 승인 노드 미결속')
    if old.header!=new.header or old.strings!=new.strings or len(old.resources)!=len(new.resources):
        raise scene.UnsupportedScene('헤더·문자열·리소스 변경')
    if nb['names'][:len(ob['names'])]!=ob['names'] or any(n not in font.FONT_PROPERTIES and n!='line_spacing' for n in nb['names'][len(ob['names']):]):
        raise scene.UnsupportedScene('글꼴 외의 장면 이름 변경')
    if len(nv)<len(ov):raise scene.UnsupportedScene('기존 variant 누락')
    try:edits=node.analyze_bundle(ob,changes)
    except node.SceneNodeError as e:raise scene.UnsupportedScene('승인 문자열 참조 불명: '+str(e)) from e
    allowed={e['variant_index']:e for e in edits}
    for i,before in enumerate(ov):
        after=nv[i]
        if i in allowed:
            e=allowed[i]
            if before.tag!=5 or after.tag!=5 or before.text!=e['original'] or after.text!=e['replacement']:
                raise scene.UnsupportedScene('승인 문자열 위치·값 불일치')
        elif before.raw!=after.raw:
            raise scene.UnsupportedScene('글꼴·문자열 외 기존 variant 변경')
    added_indices=set(); added_slots=set();spacing_paths=[]
    oldnodes,newnodes=_nodes(ob),_nodes(nb)
    if len(oldnodes)!=len(newnodes):raise scene.UnsupportedScene('노드 개수 변경')
    for before,after in zip(oldnodes,newnodes):
        path,head,op,groups=before; path2,head2,np,groups2=after
        if (path,head,groups)!=(path2,head2,groups2):raise scene.UnsupportedScene('노드 식별·순서·그룹 변경')
        names=nb['names']
        normalized=[]
        old_words={word for word,_ in op}
        # A spacing adjustment is allowed only on a node with an approved
        # text change and an actual newly-added approved font reference.
        added_font_here=any(names[w&((1<<30)-1)] in font.FONT_PROPERTIES
                            and (path,names[w&((1<<30)-1)]) in permitted and i>=len(ov)
                            for w,i in np)
        for word,index in np:
            name=names[word&((1<<30)-1)]
            is_spacing=(name=='line_spacing' and added_font_here and index>=len(ov)
                        and nv[index].raw==bytes.fromhex('0400000000000000'))
            if is_spacing:
                slot=(path,name)
                if slot in added_slots or word & ~((1<<30)-1):
                    raise scene.UnsupportedScene('줄 간격 속성 중복 또는 플래그 미지원')
                added_slots.add(slot);added_indices.add(index);spacing_paths.append(path)
                if word in old_words:normalized.append((word,None))
                continue
            is_font=(name in font.FONT_PROPERTIES and (path,name) in permitted and index>=len(ov))
            if is_font:
                slot=(path,name)
                if slot in added_slots:raise scene.UnsupportedScene('승인 글꼴 속성이 중복됨')
                if word & ~((1<<30)-1):raise scene.UnsupportedScene('글꼴 속성 플래그 미지원')
                added_slots.add(slot)
                v=nv[index]
                if v.tag!=24 or len(v.raw)!=12 or struct.unpack_from('<I',v.raw,4)[0]!=3:
                    raise scene.UnsupportedScene('새 글꼴 variant 형식 불명')
                added_indices.add(index)
                if word in old_words:normalized.append((word,None))
                continue
            normalized.append((word,index))
        if len(normalized)!=len(op):raise scene.UnsupportedScene('비글꼴 노드 속성 수 변경')
        for (ow,oi),(nw,ni) in zip(op,normalized):
            if ow!=nw or (ni is not None and oi!=ni):raise scene.UnsupportedScene('비글꼴 속성 순서 또는 참조 변경')
    if added_indices!=set(range(len(ov),len(nv))):raise scene.UnsupportedScene('새 variant가 승인된 글꼴만은 아님')
    for a,b in zip(old.resources,new.resources):
        if (a.identity_raw,a.kind_raw)!=(b.identity_raw,b.kind_raw) or len(a.properties)!=len(b.properties):
            raise scene.UnsupportedScene('내부 리소스 식별·속성 변경')
        for op,np in zip(a.properties,b.properties):
            if op.name_raw!=np.name_raw:raise scene.UnsupportedScene('속성 이름 또는 순서 변경')
            if a.identity==root and op.name=='_bundled':
                left,right=_bundle_items(op.value),_bundle_items(np.value)
                if op.value.prefix!=np.value.prefix or len(left)!=len(right):raise scene.UnsupportedScene('장면 딕셔너리 변경')
                for (ok,ovalue),(nk,nvalue) in zip(left,right):
                    if ok.raw!=nk.raw:raise scene.UnsupportedScene('장면 딕셔너리 키 변경')
                    if ok.text=='variants':
                        if (ovalue.tag!=30 or nvalue.tag!=30 or
                            (struct.unpack_from('<I',ovalue.prefix,4)[0]&0x80000000)!=(struct.unpack_from('<I',nvalue.prefix,4)[0]&0x80000000)):
                            raise scene.UnsupportedScene('variant 배열 형식 또는 공유 플래그 변경')
                    if ok.text not in ('names','nodes','variants'):
                        try:rs._compare_variant(ovalue,nvalue,('', '', ()),{},set())
                        except rs.RsrcError as e:raise scene.UnsupportedScene('그 밖의 장면 직렬화 변경: '+str(e)) from e
            else:
                try:rs._compare_variant(op.value,np.value,('', '', ()),{},set())
                except rs.RsrcError as e:raise scene.UnsupportedScene('내부 리소스 변경: '+str(e)) from e
    return {'status':'passed','locations':len(changes),'font_variants':len(added_indices),
            'spacing_paths':spacing_paths}
