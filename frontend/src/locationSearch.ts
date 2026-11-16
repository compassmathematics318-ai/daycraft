import type {Place} from './types'

export interface LocationCandidate {name:string;lat:number;lon:number;address?:Record<string,string>|string;source?:string;provider?:string;attribution?:string;match_type?:string;resolved_query?:string;alias?:string;alias_source?:string;location_id?:string}
export type LocationSearchStatus='ok'|'no_results'|'rate_limited'|'unavailable'|'timeout'|'invalid_response'|'invalid_query'|'configuration_error'
export interface LocationSearchResponse {results:LocationCandidate[];status:LocationSearchStatus;message:string}
const messages:Record<LocationSearchStatus,string>={
 ok:'Choose a result, then confirm its address and pin.',
 no_results:'No map matches found. Try a full building name or address, or choose a point manually.',
 rate_limited:'Map search is busy or rate limited. Wait a moment and try again. Saved places and manual selection are still available.',
 unavailable:'Map search is temporarily unavailable. Saved places and manual selection are still available.',
 timeout:'Map search took too long. Try again, or use a saved place or manual selection.',
 invalid_response:'The map provider returned an unreadable response. Try again, or use a saved place or manual selection.',
 invalid_query:'Enter a building name or address using at least two characters.',
 configuration_error:'Map search is not configured correctly. Saved places and manual selection are still available.',
}
export function candidateAddress(result:LocationCandidate):string {
 if(typeof result.address==='string')return result.address
 if(result.address)return [...new Set(Object.values(result.address).filter(Boolean))].join(', ')
 return result.name
}
export function candidateSource(result:LocationCandidate):string {
 const source=result.source??result.provider??(result.match_type==='saved'?'Saved place':'Map provider')
 return [result.alias?`${result.alias} → ${result.resolved_query??result.name}`:'',source,result.attribution??''].filter(Boolean).join(' · ')
}
export function savedLocationMatches(places:Place[],query:string):Place[]{const text=query.trim().toLocaleLowerCase();return places.filter(place=>[place.name,place.address,...place.aliases??[]].join(' ').toLocaleLowerCase().includes(text))}
export function normalizeLocationSearch(data:unknown,httpStatus=200):LocationSearchResponse {
 const body=data&&typeof data==='object'?data as Record<string,unknown>:{}
 const detail=body.detail&&typeof body.detail==='object'&&!Array.isArray(body.detail)?body.detail as Record<string,unknown>:body
 const results=Array.isArray(detail.results)?detail.results.filter((item):item is LocationCandidate=>!!item&&typeof item==='object'&&typeof item.name==='string'&&Number.isFinite(item.lat)&&Math.abs(item.lat)<=90&&Number.isFinite(item.lon)&&Math.abs(item.lon)<=180):[]
 const known=typeof detail.status==='string'&&Object.hasOwn(messages,detail.status)?detail.status as LocationSearchStatus:null
 const malformedSuccess=httpStatus<400&&(!known||known==='ok'||known==='no_results')&&(!Array.isArray(detail.results)||detail.results.length>0&&!results.length)
 const status:LocationSearchStatus=malformedSuccess?'invalid_response':known??(httpStatus===429?'rate_limited':httpStatus===400||httpStatus===422?'invalid_query':httpStatus===401||httpStatus===403?'configuration_error':httpStatus>=400?'unavailable':results.length?'ok':'no_results')
 const message=!malformedSuccess&&typeof detail.message==='string'&&detail.message.trim()?detail.message:messages[status]
 return {results,status,message}
}
export async function searchLocations(query:string):Promise<LocationSearchResponse>{
 if(query.trim().length<2)return {results:[],status:'invalid_query',message:messages.invalid_query}
 try{
  const response=await fetch('/api/geocode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:query.trim()})})
  let data:unknown
  try{data=await response.json()}catch{return {results:[],status:'invalid_response',message:messages.invalid_response}}
  return normalizeLocationSearch(data,response.status)
 }catch{return {results:[],status:'unavailable',message:messages.unavailable}}
}
