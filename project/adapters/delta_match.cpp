// Exhaustive COPY/ADD matcher for 64-byte substrings; build: c++ -O3 -std=c++17.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
using U64=uint64_t; using U32=uint32_t;
constexpr U32 NONE=0xffffffffu; constexpr U64 B=257;
struct Map { int fd; size_t size; const unsigned char* p; Map(const char* path){fd=open(path,O_RDONLY);struct stat st{};if(fd<0||fstat(fd,&st)||st.st_size<=0)throw std::runtime_error("파일 열기 실패");size=st.st_size;p=(const unsigned char*)mmap(nullptr,size,PROT_READ,MAP_PRIVATE,fd,0);if(p==MAP_FAILED)throw std::runtime_error("mmap 실패");} ~Map(){munmap((void*)p,size);close(fd);} };
struct Rec {uint8_t kind,category;U64 pos,len,src; U32 begin;};
struct Node { U32 target,next,match; };
struct Slot { U64 hash; U32 head,remaining; };
U64 rd64(std::istream& s){U64 x=0;for(int i=0;i<8;i++){int c=s.get();if(c<0)throw std::runtime_error("계획 파일 부족");x|=U64(c)<<(8*i);}return x;}
void wr64(std::ostream& s,U64 x){for(int i=0;i<8;i++)s.put(char(x>>(8*i)));}
U64 mix(U64 x){x^=x>>30;x*=0xbf58476d1ce4e5b9ULL;x^=x>>27;x*=0x94d049bb133111ebULL;return x^(x>>31);}
U64 hash64(const unsigned char* p){U64 h=0;for(int i=0;i<64;i++)h=h*B+p[i];return h;}
int main(int argc,char**argv){try{
 if(argc!=5 && argc!=6)throw std::runtime_error("source candidate plan output 필요");
 bool verify_only=argc==6&&std::string(argv[5])=="--verify-only";
 if(argc==6&&!verify_only)throw std::runtime_error("알 수 없는 옵션");
 Map source(argv[1]), target(argv[2]);if(source.size>=NONE||target.size>=NONE)throw std::runtime_error("4GB 이상 미지원");
 std::ifstream in(argv[3],std::ios::binary);if(!in)throw std::runtime_error("계획 열기 실패");U64 count=rd64(in);if(count>1000000)throw std::runtime_error("계획 수 초과");std::vector<Rec> recs;U64 cursor=0, windows=0;
 for(U64 i=0;i<count;i++){int kind=in.get();U64 pos=rd64(in),len=rd64(in),src=rd64(in);int cat=in.get();if(kind<0||kind>1||cat<0||cat>2||pos!=cursor||len>target.size-pos||(!kind&&(src>source.size||len>source.size-src)))throw std::runtime_error("계획 범위 오류");recs.push_back({uint8_t(kind),uint8_t(cat),pos,len,src,0});cursor+=len;if(kind&&len>=64)windows+=len-63;}
 if(cursor!=target.size||in.peek()!=EOF||windows>=NONE)throw std::runtime_error("계획 크기 오류");
 size_t cap=1;while(cap<windows*2)cap*=2;std::cerr<<"64바이트 검사 위치 "<<windows<<", 해시 슬롯 "<<cap<<"\n";
 std::vector<Slot> table(cap,Slot{0,NONE,0});std::vector<Node> nodes;nodes.reserve(windows);U64 high=1;for(int i=0;i<63;i++)high*=B;
 for(auto& r:recs)if(r.kind&&r.len>=64){r.begin=nodes.size();U64 h=hash64(target.p+r.pos);for(U64 j=0;j<=r.len-64;j++){if(j)h=(h-U64(target.p[r.pos+j-1])*high)*B+target.p[r.pos+j+63];size_t k=mix(h)&(cap-1);while(table[k].head!=NONE&&table[k].hash!=h)k=(k+1)&(cap-1);if(table[k].head==NONE)table[k].hash=h;nodes.push_back({U32(r.pos+j),table[k].head,NONE});table[k].head=nodes.size()-1;table[k].remaining++;}}
 U64 found=0;if(source.size>=64&&windows){U64 h=hash64(source.p);for(U64 j=0;j<=source.size-64;j++){if(j)h=(h-U64(source.p[j-1])*high)*B+source.p[j+63];size_t k=mix(h)&(cap-1);while(table[k].head!=NONE&&table[k].hash!=h)k=(k+1)&(cap-1);if(table[k].head!=NONE&&table[k].remaining){for(U32 n=table[k].head;n!=NONE;n=nodes[n].next)if(nodes[n].match==NONE&&!memcmp(source.p+j,target.p+nodes[n].target,64)){nodes[n].match=U32(j);table[k].remaining--;found++;}}}}
 std::cerr<<"원본과 같은 64바이트 창 "<<found<<"\n";
 if(verify_only){if(found)throw std::runtime_error("최소성 검사 실패: ADD에 원본과 같은 64바이트 포함");std::cout<<"{\"checked_windows\":"<<windows<<",\"matched\":0}\n";return 0;}
 std::ofstream out(argv[4],std::ios::binary|std::ios::trunc);if(!out)throw std::runtime_error("출력 열기 실패");out.write("KPDIF001",8);wr64(out,0);wr64(out,target.size);U64 operations=0, addbytes[3]={0,0,0}, copybytes=0;
 auto copy=[&](U64 at,U64 len){out.put(0);wr64(out,at);wr64(out,len);operations++;copybytes+=len;};
 auto add=[&](U64 at,U64 len,int cat){if(!len)return;out.put(1);wr64(out,len);out.write((const char*)target.p+at,len);operations++;addbytes[cat]+=len;};
 for(auto&r:recs){if(!r.kind){copy(r.src,r.len);continue;}U64 j=0, pending=0;while(j+64<=r.len){U32 match=nodes[r.begin+j].match;if(match==NONE){j++;continue;}add(r.pos+pending,j-pending,r.category);U64 len=64;while(j+len<r.len&&U64(match)+len<source.size&&target.p[r.pos+j+len]==source.p[U64(match)+len])len++;copy(match,len);j+=len;pending=j;}add(r.pos+pending,r.len-pending,r.category);}
 out.seekp(8);wr64(out,operations);out.close();if(!out)throw std::runtime_error("쓰기 실패");
 std::cout<<"{\"windows\":"<<windows<<",\"matched\":"<<found<<",\"operations\":"<<operations<<",\"copy\":"<<copybytes<<",\"add_header\":"<<addbytes[0]<<",\"add_changed\":"<<addbytes[1]<<",\"add_fonts\":"<<addbytes[2]<<"}\n";
 return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
