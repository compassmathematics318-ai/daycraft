import {localDate} from './utils'

export function historyDateLabel(date:string):string {
 return new Intl.DateTimeFormat('en-CA',{weekday:'short',month:'long',day:'numeric',year:'numeric',timeZone:'UTC'}).format(new Date(`${date}T12:00:00Z`))
}
export function historyTimestamp(value:string|null|undefined,timezone:string):string {
 if(!value)return 'Not recorded'
 return new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZoneName:'short'}).format(new Date(value))
}
/** Group by actual confirmation date in the user's zone; unknown dates stay unknown. */
export function groupByCompletionDay<T extends {confirmed_at:string|null}>(items:T[],timezone:string):{date:string|null;items:T[]}[]{
 const groups=new Map<string|null,T[]>()
 for(const item of items){const date=item.confirmed_at?localDate(new Date(item.confirmed_at),timezone):null;const group=groups.get(date)??[];group.push(item);groups.set(date,group)}
 return [...groups].sort(([a],[b])=>a===null?1:b===null?-1:b.localeCompare(a)).map(([date,items])=>({date,items}))
}
