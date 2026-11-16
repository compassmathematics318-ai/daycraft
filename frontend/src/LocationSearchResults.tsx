import {MapPin} from 'lucide-react'
import {candidateAddress,candidateSource} from './locationSearch'
import type {LocationCandidate,LocationSearchResponse} from './locationSearch'

export default function LocationSearchResults({response,onChoose}:{response:LocationSearchResponse|null;onChoose:(candidate:LocationCandidate)=>void}){
 if(!response)return null
 const failed=!['ok','no_results'].includes(response.status)
 return <section className="provider-results" aria-label="Map search results"><p className={failed?'inline-error':'location-help'} role={failed?'alert':'status'} data-search-status={response.status}>{response.message}</p>{response.results.length>0&&<><h3>Map search results — confirm the exact place</h3>{response.results.map((result,index)=><button className="location-provider-result" type="button" key={`${result.location_id??result.name}-${index}`} onClick={()=>onChoose(result)}><MapPin size={17}/><span><strong>{result.name}</strong><small>{candidateAddress(result)}</small><small>{candidateSource(result)}</small></span></button>)}</>}</section>
}
