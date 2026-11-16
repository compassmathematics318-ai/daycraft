import type {Activity,Occurrence} from './types'
import {localDate,localInput,localIso,nextDate} from './utils'

export function sundayOf(date:string):string {
 const weekday=new Date(`${date}T12:00:00Z`).getUTCDay()
 return nextDate(date,-weekday)
}
export function weekLabel(start:string):string {
 const first=new Date(`${start}T12:00:00Z`),last=new Date(`${nextDate(start,6)}T12:00:00Z`)
 const month=(d:Date)=>d.toLocaleDateString('en-CA',{month:'short',timeZone:'UTC'})
 if(first.getUTCFullYear()!==last.getUTCFullYear())return `${month(first)} ${first.getUTCDate()}, ${first.getUTCFullYear()} – ${month(last)} ${last.getUTCDate()}, ${last.getUTCFullYear()}`
 return `${month(first)} ${first.getUTCDate()}–${first.getUTCMonth()===last.getUTCMonth()?'':`${month(last)} `}${last.getUTCDate()}, ${last.getUTCFullYear()}`
}
export function snapMinute(value:number):number {return Math.max(0,Math.min(1435,Math.round(value/5)*5))}
export function clockMinute(minute:number):string {return `${Math.floor(minute/60).toString().padStart(2,'0')}:${(minute%60).toString().padStart(2,'0')}`}
export function wallTime(date:string,minute:number,timezone:string):string {
 const dayOffset=Math.floor(minute/1440),within=((minute%1440)+1440)%1440
 return localIso(`${nextDate(date,dayOffset)}T${clockMinute(within)}`,timezone)
}
export function localMinute(instant:string,timezone:string):number {
 const clock=localInput(instant,timezone).slice(11)
 return Number(clock.slice(0,2))*60+Number(clock.slice(3,5))
}
/** Metadata-only edits must preserve a saved instant in a repeated DST hour. */
export function calendarInputInstant(value:string,timezone:string,original?:string|null):string {
 return original&&localInput(original,timezone)===value?original:localIso(value,timezone)
}
export function placementAt(activity_id:string,date:string,minute:number,duration=60,timezone='America/Toronto') {
 const start=wallTime(date,snapMinute(minute),timezone)
 return {activity_id,start,end:new Date(Date.parse(start)+duration*60000).toISOString()}
}
/** Fast drag feedback; the server still validates every persisted placement. */
export function placementIssue(activity:Activity,value:{start:string;end:string},items:Occurrence[],timezone:string,excludeId?:string):string|null {
 const first=localDate(new Date(value.start),timezone),last=localDate(new Date(Date.parse(value.end)-1),timezone)
 if(activity.start_date&&first<activity.start_date)return "Before this block's start date"
 if(activity.end_date&&last>activity.end_date)return "After this block's end date"
 if(items.some(item=>item.id!==excludeId&&Date.parse(item.start)<Date.parse(value.end)&&Date.parse(item.end)>Date.parse(value.start)))return 'Overlaps another meeting'
 return null
}
export function dateLabel(date:string):string {return new Date(`${date}T12:00:00Z`).toLocaleDateString('en-CA',{weekday:'long',month:'short',day:'numeric',timeZone:'UTC'})}
export function occurrenceOnDate(item:Occurrence,date:string,timezone:string):boolean {
 const from=wallTime(date,0,timezone),until=wallTime(nextDate(date,1),0,timezone)
 return Date.parse(item.start)<Date.parse(until)&&Date.parse(item.end)>Date.parse(from)
}
export function eventSlice(item:Occurrence,date:string,timezone:string):{top:number;height:number} {
 const firstDay=localDate(new Date(item.start),timezone),lastDay=localDate(new Date(item.end),timezone)
 const top=firstDay<date?0:localMinute(item.start,timezone)
 const bottom=lastDay>date?1440:localMinute(item.end,timezone)
 return {top,height:Math.max(5,bottom-top)}
}

export function calendarOverlaps(items:Occurrence[]):[Occurrence,Occurrence][] {
 const sorted=[...items].sort((a,b)=>Date.parse(a.start)-Date.parse(b.start)),pairs:[Occurrence,Occurrence][]=[]
 for(let i=0;i<sorted.length;i++)for(let j=i+1;j<sorted.length&&Date.parse(sorted[j].start)<Date.parse(sorted[i].end);j++)if(sorted[i].id!==sorted[j].id)pairs.push([sorted[i],sorted[j]])
 return pairs
}

export function eventLanes(items:Occurrence[]):Map<string,{lane:number;columns:number}> {
 const result=new Map<string,{lane:number;columns:number}>(),sorted=[...items].sort((a,b)=>Date.parse(a.start)-Date.parse(b.start))
 let group:Occurrence[]=[],groupEnd=-Infinity
 const flush=()=>{const ends:number[]=[],placements:{item:Occurrence;lane:number}[]=[];for(const item of group){let lane=ends.findIndex(end=>end<=Date.parse(item.start));if(lane<0)lane=ends.length;ends[lane]=Date.parse(item.end);placements.push({item,lane})}for(const p of placements)result.set(p.item.id,{lane:p.lane,columns:ends.length})}
 for(const item of sorted){if(Date.parse(item.start)>=groupEnd){flush();group=[];groupEnd=-Infinity}group.push(item);groupEnd=Math.max(groupEnd,Date.parse(item.end))}flush();return result
}
