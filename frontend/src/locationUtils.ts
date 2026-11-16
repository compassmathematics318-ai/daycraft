import type {Block,LocationMode,LocationReference,LocationValue,Place} from './types'
import {localDate} from './utils'
import {capabilityName} from './venueUtils'
export const locationModes:Record<LocationMode,string>={unspecified:'Unspecified',remote:'Remote / online',preferred:'Preferred place',required:'Required place'}
export const locationMode=(value:LocationValue):LocationMode=>value.location_mode??(value.location_id?'required':'unspecified')
export const locationDetails=(place:Place)=>[place.building,place.room&&`Room ${place.room}`,place.floor&&`Floor ${place.floor}`,place.entrance&&`Entrance: ${place.entrance}`].filter(Boolean).join(' · ')
export function referenceCategory(reference:LocationReference):'class'|'assessment'|'commitment'|'task'{if(reference.source==='activity'||reference.source==='occurrence'){const category=reference.category??reference.type;if(category==='class'||category==='assessment'||category==='commitment')return category}return 'task'}
export interface ReferenceOptions {filter:string;query:string;scope:'week'|'day';day:string;definitions:boolean;timezone:string}
function datedVisible(reference:LocationReference,options:ReferenceOptions){
 const startDay=reference.start?localDate(new Date(reference.start),options.timezone):null
 const lastDay=reference.end?localDate(new Date(Math.max(Date.parse(reference.start??reference.end),Date.parse(reference.end)-1)),options.timezone):startDay
 return !!startDay&&(options.scope==='week'||startDay<=options.day&&!!lastDay&&lastDay>=options.day)
}
export function filteredReference(reference:LocationReference,options:ReferenceOptions,place?:Place):LocationReference|null {
 const query=options.query.trim().toLowerCase()
 if(options.filter!=='all'&&referenceCategory(reference)!==options.filter)return null
 if(query&&![reference.title,place?.name,place?.address,...(place?.aliases??[])].join(' ').toLowerCase().includes(query))return null
 if(reference.occurrences){
  const occurrences=reference.occurrences.filter(item=>datedVisible(item,options))
  const placements=(reference.placements??[]).filter(item=>!item.start)
  if(!occurrences.length&&!(options.definitions&&placements.length))return null
  return {...reference,occurrences,occurrence_count:occurrences.length,placements:options.definitions?placements:[]}
 }
 return (reference.start?datedVisible(reference,options):options.definitions)?reference:null
}
export function referenceVisible(reference:LocationReference,options:ReferenceOptions,place?:Place){return filteredReference(reference,options,place)!==null}
export function groupNearbyPlaces<T extends Place & {references:LocationReference[]}>(places:T[]){
 const groups:{lat:number;lon:number;places:T[];count:number}[]=[]
 for(const place of places){const group=groups.find(group=>{const longitudeScale=Math.cos((group.lat+place.lat)/2*Math.PI/180)*111320;const longitudeDifference=((group.lon-place.lon+540)%360)-180;return Math.hypot((group.lat-place.lat)*111320,longitudeDifference*longitudeScale)<25});if(group){group.places.push(place);group.count+=place.references.length}else groups.push({lat:place.lat,lon:place.lon,places:[place],count:place.references.length})}
 return groups
}

export function alternativeLocationPolicy(value:LocationValue) {
 const allowed=locationMode(value)==='preferred'&&!!value.location_id&&value.allow_alternative_locations===true
 return {allow_alternative_locations:allowed,alternative_location_ids:allowed?[...new Set(value.alternative_location_ids??[])].filter(id=>id!==value.location_id):[]}
}
// Pick explicitly: form values may contain task identity or other protected fields.
export function locationFields(value:LocationValue):LocationValue {
 return {location_id:value.location_id,location_mode:locationMode(value),room:value.room??'',location_requirements:[...value.location_requirements??[]],...alternativeLocationPolicy(value)}
}
export function locationSelectionChange(previous:LocationValue,next:LocationValue):LocationValue {
 const physical=!!next.location_id&&['required','preferred'].includes(locationMode(next))
 const unchanged=next.location_id===previous.location_id&&locationMode(next)===locationMode(previous)
 return {...next,location_requirements:[...next.location_requirements??previous.location_requirements??[]],room:physical&&next.location_id===previous.location_id?previous.room??'':'',...alternativeLocationPolicy(unchanged?{...previous,...next}:next)}
}
export function plannedLocation(block:Pick<Block,'location_id'|'location_mode'|'resolved_location_id'>,name:(id:string|null)=>string):string {
 const actual=block.resolved_location_id===undefined?block.location_id:block.resolved_location_id
 const mode=locationMode(block)
 if(mode==='remote')return actual?`Remote / online; assumed position: ${name(actual)}`:'Remote / online; physical position unknown'
 if(mode==='unspecified')return 'Location unspecified; physical position unverified'
 if(mode==='preferred')return `Planned: ${actual?name(actual):'unresolved'}; Preferred: ${name(block.location_id)}`
 return actual?name(actual):'Physical location unresolved'
}
export function locationPermission(value:LocationValue & Pick<Block,'resolved_location_id'|'location_suitability'>,name:(id:string|null)=>string):string {
 if(locationMode(value)!=='preferred')return ''
 const suitability=value.location_suitability
 if(!suitability)return 'Preferred place is flexible; reoptimize to review suitability evidence.'
 const actual=value.resolved_location_id??value.location_id
 const selected=suitability.candidates.find(candidate=>candidate.location_id===actual)
 if(actual!==value.location_id&&selected)return selected.source==='user_confirmed'?`You confirmed ${name(actual)} is suitable.`:`${name(actual)} matches the venue needs; access is confirmed.`
 if(actual!==value.location_id&&!selected)return 'Saved venue evidence needs review. Reoptimize unstarted work.'
 if(suitability.candidates.length<=1)return suitability.limitation||'No other suitable venue is verified. The preference remains flexible.'
 return `${suitability.candidates.length-1} supported alternative${suitability.candidates.length===2?'':'s'} considered with travel and timing.`
}
export function venueRequirementsSummary(block:Pick<Block,'location_suitability'>):string {
 const suitability=block.location_suitability
 if(!suitability)return 'Venue needs have not been assessed for this saved plan.'
 if(!suitability.requirements.length)return 'Venue needs are uncertain; add optional needs or confirm a suitable place.'
 return `${suitability.source==='explicit'?'Your venue needs':'Inferred venue needs'}: ${suitability.requirements.map(capabilityName).join(', ')}.`
}

// Display-only retirement of two exact sentences from pre-semantic saved plans.
// Evidence-bearing plans and every unrelated sentence retain their original text.
function legacyVenueText(text:string):string {
 return text.replaceAll('Scheduled at the configured preferred venue; alternative venues are not permitted.','').replaceAll('Required and preferred venues stay selected unless a preferred activity explicitly permits a listed alternative; travel uses the actual venue.','').replace(/\s{2,}/g,' ').trim()
}
export function displayBlockRationale(block:LocationValue & Pick<Block,'rationale'|'location_suitability'>):string {
 return locationMode(block)==='preferred'&&!block.location_suitability?legacyVenueText(block.rationale):block.rationale
}
export function displayCardRationale(block:LocationValue & Pick<Block,'rationale'|'location_suitability'>):string {
 const rationale=displayBlockRationale(block)
 // Actual/preferred labels and the suitability summary already explain the venue.
 // Keep full evidence in the activity details, rather than repeating it on cards.
 return block.location_suitability?rationale.split(' Scheduled at ')[0].trim():rationale
}
export function displayScheduleExplanations(schedule:Pick<import('./types').Schedule,'blocks'|'explanations'>):string[] {
 return schedule.blocks.some(block=>locationMode(block)==='preferred'&&!block.location_suitability)?schedule.explanations.map(legacyVenueText).filter(Boolean):schedule.explanations
}
