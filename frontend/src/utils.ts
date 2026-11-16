import type {ClassItem} from './types'
export function localDate(date=new Date(),timezone='America/Toronto'):string {
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date)
  return `${parts.find(p=>p.type==='year')!.value}-${parts.find(p=>p.type==='month')!.value}-${parts.find(p=>p.type==='day')!.value}`
}
export function nextDate(date:string,days:number):string {const d=new Date(`${date}T12:00:00Z`);d.setUTCDate(d.getUTCDate()+days);return d.toISOString().slice(0,10)}
export function duration(minutes:number):string {if(minutes<60)return `${Math.round(minutes)}m`;const rest=Math.round(minutes%60);return `${Math.floor(minutes/60)}h${rest?` ${rest}m`:''}`}
export function time(iso:string,timezone='America/Toronto'):string {return new Intl.DateTimeFormat('en-CA',{timeZone:timezone,hour:'numeric',minute:'2-digit'}).format(new Date(iso))}
export function localInput(iso:string,timezone='America/Toronto'):string {const p=new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(iso));const part=(n:string)=>p.find(x=>x.type===n)?.value;return `${part('year')}-${part('month')}-${part('day')}T${part('hour')}:${part('minute')}`}
export function minutesBetween(start:string,end:string):number {return Math.round((new Date(end).getTime()-new Date(start).getTime())/60000)}
export function classOnDate(c:ClassItem,date:string):boolean {if(c.exceptions.includes(date))return false;if(c.date)return c.date===date;const day=(new Date(`${date}T12:00:00Z`).getUTCDay()+6)%7;return c.weekdays.includes(day)&&(!c.start_date||c.start_date<=date)&&(!c.end_date||c.end_date>=date)}
export function errorMessage(error:unknown):string {return error instanceof Error?error.message:'Something went wrong. Please try again.'}
export async function api<T>(path:string,method='GET',body?:unknown):Promise<T>{const response=await fetch(`/api${path}`,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});if(!response.ok){let detail:unknown;try{const data=await response.json();detail=data.detail??data.message}catch{detail=response.statusText}if(Array.isArray(detail))detail=detail.map((x:{msg?:string;loc?:string[]})=>`${x.loc?.slice(1).join('.')??''}: ${x.msg??JSON.stringify(x)}`).join('; ');throw new Error(typeof detail==='string'?detail:JSON.stringify(detail))}if(response.status===204)return undefined as T;return response.json() as Promise<T>}

/** Interpret a wall-clock input in the chosen IANA zone, rejecting DST gaps.
 * A repeated fall-back time resolves to its earliest occurrence deterministically.
 */
export function localIso(value:string,timezone:string):string {
 if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value))throw new Error('Enter a valid date and time.')
 const target=Date.parse(`${value}:00Z`)
 if(!Number.isFinite(target)||new Date(target).toISOString().slice(0,16)!==value)throw new Error('Enter a valid date and time.')
 let guess=target
 for(let i=0;i<5;i++){const represented=Date.parse(`${localInput(new Date(guess).toISOString(),timezone)}:00Z`);const difference=target-represented;if(!difference)break;guess+=difference}
 if(localInput(new Date(guess).toISOString(),timezone)!==value)throw new Error(`This time does not exist in ${timezone} because the clock moves forward. Choose a later time.`)
 const candidates=[guess]
 for(let offset=-180;offset<=180;offset+=30){const candidate=guess+offset*60000;if(localInput(new Date(candidate).toISOString(),timezone)===value)candidates.push(candidate)}
 return new Date(Math.min(...candidates)).toISOString()
}

export function availableMinutes(start:string,end:string,intervals:{start:string;end:string}[]):number {
 const lower=Date.parse(start),upper=Date.parse(end)
 if(!Number.isFinite(lower)||!Number.isFinite(upper)||upper<=lower)return 0
 const ranges=intervals.map(b=>[Math.max(lower,Date.parse(b.start)),Math.min(upper,Date.parse(b.end))]).filter(([a,b])=>b>a).sort((a,b)=>a[0]-b[0])
 let covered=0,cursor=lower
 for(const [a,b] of ranges){if(b>cursor){covered+=b-Math.max(cursor,a);cursor=b}}
 return Math.max(0,Math.round((upper-lower-covered)/60000))
}

export function chronological<T extends {start:string}>(items:T[]):T[]{return [...items].sort((a,b)=>Date.parse(a.start)-Date.parse(b.start))}
