import { mkdirSync, writeFileSync, copyFileSync, readFileSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../../..");
if (!process.argv[2]) throw new Error("Pass the cli.exe built from v0.3.49 with customization/v0.3.49-traffic-pi.patch.");
const cli = resolve(process.argv[2]);
const work = join(root, ".next/highway-build");
mkdirSync(join(work, "data"), { recursive: true });
const gps = (x, y) => [106.7 + x / 96700, 29.7 + y / 111200];
const boundary = [[0,-320],[2000,-320],[2000,320],[0,320],[0,-320]].map(([x,y]) => gps(x,y));
writeFileSync(join(here, "boundary.geojson"), JSON.stringify({type:"FeatureCollection",features:[{type:"Feature",properties:{name:"Traffic Pi synthetic motorway"},geometry:{type:"Polygon",coordinates:[boundary]}}]}, null, 2));
const nodes = [], ways = [];
const node = (x,y) => { const id=nodes.length+1; const [lon,lat]=gps(x,y); nodes.push(`<node id="${id}" lon="${lon}" lat="${lat}"/>`); return id; };
const road = (id,name,refs,lanes=3) => ways.push(`<way id="${id}">${refs.map(ref=>`<nd ref="${ref}"/>`).join("")}<tag k="name" v="${name}"/><tag k="highway" v="${lanes===3?"motorway":"motorway_link"}"/><tag k="oneway" v="yes"/><tag k="lanes" v="${lanes}"/><tag k="maxspeed" v="${lanes===3?90:50}"/><tag k="sidewalk" v="no"/><tag k="bicycle" v="no"/><tag k="foot" v="no"/></way>`);
const east = [-120,500,1400,2120].map(x=>node(x,-22));
const west = [2120,1400,500,-120].map(x=>node(x,22));
road(100,"高速主线 · 东向",east); road(101,"高速主线 · 西向",west);
const entryEast=node(180,-220), exitEast=node(1830,-220);
const entryWest=node(1820,220), exitWest=node(170,220);
road(102,"东向入口匝道",[node(-120,-260),entryEast,node(360,-120),east[1]],1);
road(103,"东向出口匝道",[east[2],node(1570,-120),exitEast,node(2120,-260)],1);
road(104,"西向入口匝道",[node(2120,260),entryWest,node(1640,120),west[1]],1);
road(105,"西向出口匝道",[west[2],node(430,120),exitWest,node(-120,260)],1);
road(106,"东侧立交连接匝道",[exitEast,node(1930,-140),node(1950,100),entryWest],1);
road(107,"西侧立交连接匝道",[exitWest,node(70,140),node(50,-100),entryEast],1);
const osm = join(here,"highway-demo.osm");
writeFileSync(osm, `<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6" generator="Traffic Pi synthetic highway">\n${nodes.join("\n")}\n${ways.join("\n")}\n</osm>\n`);
function run(args, output) {
  const result=spawnSync(cli,args,{cwd:work,encoding:"utf8",maxBuffer:32*1024*1024});
  if(result.status!==0)throw new Error(`${args[0]} failed: ${result.stderr}\n${result.stdout}`);
  if(output)writeFileSync(output,result.stdout); else console.log(result.stdout.split(/\r?\n/).slice(-6).join("\n"));
}
run(["oneshot-import",osm,"--clip-path",join(here,"boundary.geojson")]);
const map = join(work,"data/system/cn/chongqing/maps/highway-demo.bin").replaceAll("\\", "/");
const people=[];
const point=(x,y)=>({Position:{longitude:gps(x,y)[0],latitude:gps(x,y)[1]}});
const time=seconds=>seconds*10000;
for(let seconds=7*3600+58*60;seconds<8*3600+32*60;seconds+=4){
  for(const direction of [1,-1]){
    const x=direction===1?-140:2140, y=direction===1?-22:22;
    const exit=(seconds/4)%3===0;
    people.push({trips:[{departure:time(seconds),origin:point(x,y),destination:point(2000-x,exit?direction*-260:y),mode:"Drive",purpose:"Work"}]});
    if(seconds%8===0)people.push({trips:[{departure:time(seconds+1),origin:point(x,direction*-260),destination:point(2000-x,y),mode:"Drive",purpose:"Work"}]});
  }
}
const demand = join(here,"demand.json");
writeFileSync(demand,JSON.stringify({scenario_name:"motorway",people}));
run(["import-scenario","--input",demand,"--map",map]);
run(["dump-json",map],join(work,"map.json"));
const imported=JSON.parse(readFileSync(join(work,"map.json"),"utf8"));
if (imported.roads.length < 16) throw new Error("Importer discarded part of the highway network.");
for (const road of imported.roads.filter(road=>road.osm_tags.highway==="motorway")) {
  if (road.lanes.filter(lane=>lane.lane_type==="Driving").length!==3) throw new Error("Main carriageways must have three driving lanes.");
}
if (Object.keys(imported.traffic_signals).length) throw new Error("Motorway must not contain traffic signals.");
const destination=join(root,"third-party/abstreet/web/0.3.49/data/system/cn/chongqing");
for(const path of ["maps/highway-demo.bin","scenarios/highway-demo/motorway.bin"]){
  mkdirSync(dirname(join(destination,path)),{recursive:true});
  copyFileSync(join(work,"data/system/cn/chongqing",path),join(destination,path));
}
console.log(`Generated synthetic motorway with ${people.length} trips, seed 42 at runtime.`);
