import {displayCardRationale} from './locationUtils'
import {locationFields} from './locationUtils'
import {describe,expect,it} from 'vitest'
import {groupNearbyPlaces,locationDetails,locationMode,referenceVisible,referenceCategory,filteredReference,locationSelectionChange,alternativeLocationPolicy,plannedLocation,locationPermission,venueRequirementsSummary,displayBlockRationale,displayScheduleExplanations} from './locationUtils'
import type {LocationReference,Place} from './types'
const reference:LocationReference={id:'r',entity_id:'a',source:'activity',title:'Calculus',type:'class',start:null,end:null,location_mode:'required',edit_target:{kind:'activity',id:'a'}}
const place:Place={id:'mc',name:'Mathematics and Computer',lat:43.47,lon:-80.54,notes:'',address:'200 University Avenue',aliases:['MC'],travel_overrides:{},room:'4040',floor:'4',entrance:'West'}
const options={filter:'all',query:'',scope:'week' as const,day:'2026-11-11',definitions:true,timezone:'America/Toronto'}
describe('shared location semantics and overview',()=>{
 it('preserves unknown versus remote and infers physical legacy locations',()=>{expect(locationMode({location_id:null})).toBe('unspecified');expect(locationMode({location_id:null,location_mode:'remote'})).toBe('remote');expect(locationMode({location_id:'mc'})).toBe('required');expect(locationMode({location_id:'mc',location_mode:'preferred'})).toBe('preferred')})
 it('searches saved aliases and separates definitions from actual time',()=>{expect(referenceVisible(reference,{...options,query:'MC'},place)).toBe(true);expect(referenceVisible(reference,{...options,definitions:false},place)).toBe(false);expect(referenceVisible({...reference,source:'task_week'},{...options,definitions:false},place)).toBe(false);expect(referenceVisible({...reference,start:'2026-11-12T02:00:00Z'},{...options,scope:'day'},place)).toBe(true);expect(referenceVisible({...reference,start:'2026-11-12T15:00:00Z'},{...options,scope:'day'},place)).toBe(false)})
 it('normalizes activity subtypes and task types into map categories',()=>{expect(referenceCategory({...reference,type:'Lecture',category:'class'})).toBe('class');expect(referenceVisible({...reference,type:'Lecture',category:'class'},{...options,filter:'class'})).toBe(true);expect(referenceCategory({...reference,source:'task_week',type:'academic',category:'academic'})).toBe('task');expect(referenceVisible({...reference,source:'task_week',type:'academic'},{...options,filter:'task'})).toBe(true)})
 it('includes overnight meetings on every intersecting local day and excludes an end at midnight',()=>{const overnight={...reference,start:'2026-11-11T04:00:00Z',end:'2026-11-11T07:00:00Z'};expect(referenceVisible(overnight,{...options,scope:'day',day:'2026-11-10'})).toBe(true);expect(referenceVisible(overnight,{...options,scope:'day'})).toBe(true);expect(referenceVisible({...overnight,end:'2026-11-11T05:00:00Z'},{...options,scope:'day'})).toBe(false)})
 it('groups nearby longitude points in high latitudes and across the date line',()=>{expect(groupNearbyPlaces([{...place,lat:80,lon:10,references:[reference]},{...place,id:'nearby',lat:80,lon:10.001,references:[reference]}])).toHaveLength(1);expect(groupNearbyPlaces([{...place,lat:0,lon:179.99995,references:[reference]},{...place,id:'nearby',lat:0,lon:-179.99995,references:[reference]}])).toHaveLength(1)})
 it('retains exact places and references when nearby points share a pin',()=>{const groups=groupNearbyPlaces([{...place,references:[reference]},{...place,id:'mc-entrance',lat:place.lat+.0001,references:[{...reference,id:'r2'}]},{...place,id:'distant',lat:44,references:[reference]}]);expect(groups).toHaveLength(2);expect(groups[0].count).toBe(2);expect(groups[0].places.map(p=>p.id)).toEqual(['mc','mc-entrance']);expect(groups[0].places[1].references[0].id).toBe('r2')})
 it('shows optional physical instructions without requiring coordinates to change',()=>{expect(locationDetails(place)).toBe('Room 4040 · Floor 4 · Entrance: West')})
})


describe('grouped map references',()=>{
 const monday={...reference,id:'meeting-mon',source:'occurrence' as const,start:'2026-11-09T14:00:00Z',end:'2026-11-09T15:00:00Z',edit_target:{kind:'occurrence' as const,id:'meeting-mon'}}
 const wednesday={...monday,id:'meeting-wed',start:'2026-11-11T14:00:00Z',end:'2026-11-11T15:00:00Z'}
 const grouped={...reference,id:'activity:a',occurrences:[monday,wednesday],placements:[reference,monday,wednesday],occurrence_count:2}
 it('counts one stable activity while retaining separately editable dated occurrences',()=>{const result=filteredReference(grouped,options,place)!;expect(result.id).toBe('activity:a');expect(result.occurrences).toHaveLength(2);expect(groupNearbyPlaces([{...place,references:[result]}])[0].count).toBe(1);expect(result.occurrences![0].edit_target.kind).toBe('occurrence')})
 it('applies day and definition filters to the nested times used by list, popup and pin',()=>{const result=filteredReference(grouped,{...options,scope:'day',definitions:false},place)!;expect(result.occurrences?.map(item=>item.id)).toEqual(['meeting-wed']);expect(result.occurrence_count).toBe(1);expect(result.placements).toEqual([]);expect(filteredReference(grouped,{...options,scope:'day',day:'2026-11-12',definitions:false},place)).toBeNull();expect(filteredReference(grouped,{...options,scope:'day',day:'2026-11-12'},place)?.occurrences).toEqual([])})
 it('keeps distinct identities even with identical titles',()=>{const other={...grouped,id:'activity:b',entity_id:'b'};expect(groupNearbyPlaces([{...place,references:[grouped,other]}])[0].count).toBe(2)})
 it('retains category and alias search filtering for grouped entries',()=>{expect(filteredReference(grouped,{...options,query:'MC'},place)).not.toBeNull();expect(filteredReference(grouped,{...options,filter:'task'},place)).toBeNull();expect(filteredReference(grouped,{...options,query:'unrelated'},place)).toBeNull()})
})
describe('room follows a selected physical location',()=>{
 const previous={location_id:'mc',location_mode:'required' as const,room:'4040'}
 it('retains room when confirming the same physical place or changing required/preferred meaning',()=>expect(locationSelectionChange(previous,{location_id:'mc',location_mode:'preferred'}).room).toBe('4040'))
 it.each([{location_id:'dc',location_mode:'required' as const},{location_id:null,location_mode:'unspecified' as const},{location_id:null,location_mode:'remote' as const}])('clears room when selecting %o',next=>{expect(locationSelectionChange(previous,next).room).toBe('');expect(previous.room).toBe('4040')})
})

describe('preferred venue evidence and optional confirmations',()=>{
 const preferred={location_id:'pac',location_mode:'preferred' as const,room:'Gym 1'}
 const flexible={...preferred,allow_alternative_locations:true,alternative_location_ids:['pac','field','field']}
 it('keeps manual confirmation separate from semantic alternatives and ignores it for nonpreferred modes',()=>{
  expect(alternativeLocationPolicy(preferred)).toEqual({allow_alternative_locations:false,alternative_location_ids:[]})
  for(const location_mode of ['required','remote','unspecified'] as const)expect(alternativeLocationPolicy({...flexible,location_mode})).toEqual({allow_alternative_locations:false,alternative_location_ids:[]})
 })
 it('retains only explicit alternative IDs and does not mutate stored policy',()=>{
  expect(alternativeLocationPolicy(flexible)).toEqual({allow_alternative_locations:true,alternative_location_ids:['field']})
  expect(flexible.alternative_location_ids).toEqual(['pac','field','field'])
 })
 it('retains permission on confirming the same preferred place and clears it on primary or mode changes',()=>{
  expect(locationSelectionChange(flexible,preferred).alternative_location_ids).toEqual(['field'])
  for(const next of [{location_id:'mc',location_mode:'preferred' as const},{location_id:'pac',location_mode:'required' as const},{location_id:null,location_mode:'remote' as const}])expect(locationSelectionChange(flexible,next)).toMatchObject({allow_alternative_locations:false,alternative_location_ids:[]})
 })
 const name=(id:string|null)=>id==='pac'?'PAC':id==='mc'?'MC':id==='field'?'Field':'Unknown'
 it('shows saved actual venue separately from configured preference, including invalid old plans',()=>{
  expect(plannedLocation({...preferred,resolved_location_id:'mc'},name)).toBe('Planned: MC; Preferred: PAC')
  expect(plannedLocation({...preferred,resolved_location_id:null},name)).toBe('Planned: unresolved; Preferred: PAC')
  expect(locationPermission(preferred,name)).toBe('Preferred place is flexible; reoptimize to review suitability evidence.')
  expect(locationPermission(flexible,name)).toBe('Preferred place is flexible; reoptimize to review suitability evidence.')
 })
 it('does not imply a known physical destination for unspecified or remote work',()=>{
  expect(plannedLocation({location_id:null,location_mode:'unspecified',resolved_location_id:'mc'},name)).toBe('Location unspecified; physical position unverified')
  expect(plannedLocation({location_id:null,location_mode:'remote',resolved_location_id:null},name)).toBe('Remote / online; physical position unknown')
  expect(plannedLocation({location_id:null,location_mode:'remote',resolved_location_id:'mc'},name)).toBe('Remote / online; assumed position: MC')
 })
})

it('location picker output excludes task identity and protected weekly fields',()=>{
 const definition={id:'gym',session_minutes:90,recurrence:{start_week:'2026-11-08'},location_id:'pac',location_mode:'preferred' as const,room:'Gym',allow_alternative_locations:true,alternative_location_ids:['annex']}
 expect(locationFields(definition)).toEqual({location_id:'pac',location_mode:'preferred',room:'Gym',location_requirements:[],allow_alternative_locations:true,alternative_location_ids:['annex']})
})

it('does not label a historical venue unauthorized merely because it lacks a manual confirmation',()=>{
 expect(locationPermission({location_id:'pac',location_mode:'preferred',resolved_location_id:'mc'},id=>id??'Unknown')).toContain('reoptimize to review suitability evidence')
})

const suitability={requirements:['quiet_workspace','wifi'],source:'inferred' as const,confidence:'high' as const,candidates:[{location_id:'pac',source:'selected' as const,confidence:'high' as const,evidence:'Selected preference.'},{location_id:'library',source:'verified_capabilities' as const,confidence:'high' as const,evidence:'Quiet workspace and Wi-Fi verified; access confirmed.'}],limitation:''}
it('shows evidence-backed alternatives independently of the legacy manual permission flag',()=>{
 const value={location_id:'pac',location_mode:'preferred' as const,allow_alternative_locations:false,resolved_location_id:'library',location_suitability:suitability}
 expect(locationPermission(value,id=>id??'Unknown')).toBe('library matches the venue needs; access is confirmed.')
 expect(venueRequirementsSummary(value)).toBe('Inferred venue needs: Quiet workspace, Wi-Fi.')
 expect(locationPermission({...value,resolved_location_id:'pac'},id=>id??'Unknown')).toBe('1 supported alternative considered with travel and timing.')
})
it('distinguishes a lack of supported alternatives from a required destination',()=>{
 const value={location_id:'pac',location_mode:'preferred' as const,location_suitability:{...suitability,candidates:suitability.candidates.slice(0,1),limitation:'No other suitable venue is verified.'}}
 expect(locationPermission(value,id=>id??'Unknown')).toBe('No other suitable venue is verified.')
 expect(locationPermission({...value,location_mode:'required'},id=>id??'Unknown')).toBe('')
})
it('keeps explicit venue needs across picker changes without leaking definition fields',()=>{
 const previous={id:'secret-task',location_id:'pac',location_mode:'preferred' as const,location_requirements:['weights','fitness_training']}
 const changed=locationSelectionChange(previous,{location_id:'field',location_mode:'preferred'})
 expect(locationFields(changed).location_requirements).toEqual(['weights','fitness_training'])
 expect(locationFields(changed)).not.toHaveProperty('id')
 expect(locationFields({...previous,location_requirements:[]}).location_requirements).toEqual([])
})

it.each([{location_id:'other',location_mode:'preferred' as const},{location_id:'pac',location_mode:'required' as const},{location_id:null,location_mode:'remote' as const},{location_id:null,location_mode:'unspecified' as const}])('retains activity venue needs when switching location or mode to %o',next=>{
 const previous={location_id:'pac',location_mode:'preferred' as const,location_requirements:['weights','fitness_training'],allow_alternative_locations:true,alternative_location_ids:['annex']}
 const changed=locationSelectionChange(previous,next)
 expect(changed.location_requirements).toEqual(['weights','fitness_training'])
 expect(changed.alternative_location_ids).toEqual([])
 expect(previous.alternative_location_ids).toEqual(['annex'])
})

describe('legacy venue explanation display',()=>{
 const obsolete='Scheduled at the configured preferred venue; alternative venues are not permitted.'
 const rationale=`Priority 3/5; scheduled within available hours. ${obsolete}`
 const preferred={location_id:'pac',location_mode:'preferred' as const,rationale}
 const explanation='Remote sessions retain the current physical position. Required and preferred venues stay selected unless a preferred activity explicitly permits a listed alternative; travel uses the actual venue.'
 it('removes the known obsolete sentence while preserving priority and unrelated reasons without mutating saved data',()=>{
  expect(displayBlockRationale(preferred)).toBe('Priority 3/5; scheduled within available hours.')
  expect(preferred.rationale).toBe(rationale)
  expect(displayBlockRationale({...preferred,rationale:'Priority 3/5. An alternative requires a booking.'})).toBe('Priority 3/5. An alternative requires a booking.')
 })
 it('retains evidence-bearing new rationale and required-location rationale verbatim',()=>{
  expect(displayBlockRationale({...preferred,location_suitability:suitability})).toBe(rationale)
  expect(displayBlockRationale({...preferred,location_mode:'required'})).toBe(rationale)
 })
 it('removes only the exact obsolete schedule venue sentence for a legacy preferred plan',()=>{
  const schedule={blocks:[preferred],explanations:[explanation,'Deadlines and travel remain constraints.']}
  expect(displayScheduleExplanations(schedule as Parameters<typeof displayScheduleExplanations>[0])).toEqual(['Remote sessions retain the current physical position.','Deadlines and travel remain constraints.'])
  expect(schedule.explanations[0]).toBe(explanation)
  expect(displayScheduleExplanations({...schedule,blocks:[{...preferred,location_suitability:suitability}]} as Parameters<typeof displayScheduleExplanations>[0])).toEqual(schedule.explanations)
 })
})

it('keeps venue evidence in details without repeating it on schedule cards',()=>{
 const block={location_id:'pac',location_mode:'preferred' as const,rationale:'Priority 4/5; scheduled within available hours. Scheduled at a verified suitable alternative venue; the configured preferred venue remains unchanged. Venue evidence: Confirmed details.',location_suitability:{requirements:['fitness_training'],source:'inferred' as const,confidence:'high' as const,candidates:[],limitation:''}}
 expect(displayCardRationale(block)).toBe('Priority 4/5; scheduled within available hours.')
 expect(displayBlockRationale(block)).toContain('Venue evidence: Confirmed details.')
 expect(block.rationale).toContain('Scheduled at a verified suitable alternative')
})
