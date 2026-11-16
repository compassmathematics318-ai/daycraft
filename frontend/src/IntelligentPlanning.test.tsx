import {describe,expect,it,vi} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import {SettingsView} from './Forms'
import {AppliedWorkload,HorizonPanel,PlanStaleNote,isPlanStale} from './PlanContext'
import {estimatedWorkCapacity} from './planningUtils'
import {defaultSettings} from './types'
import type {Schedule} from './types'
vi.mock('./LocationPicker',()=>({default:()=>null}))
const plan:Schedule={id:'plan',date:'2032-03-07',mode:'deadline',status:'feasible',solver_status:'FEASIBLE',blocks:[],unallocated:[],conflicts:[],explanations:[],stats:{},workload_level:'low'}
describe('flexible meal preferences',()=>{
 it('defaults new profiles to breakfast 30, lunch 45 and dinner 30 without clock appointments',()=>{
  expect(defaultSettings.meals.map(({name,duration_minutes,time})=>[name,duration_minutes,time])).toEqual([['Breakfast',30,undefined],['Lunch',45,undefined],['Dinner',30,undefined]])
 })
 it('renders custom names, durations, inclusion and optional venues without exposing stored start times',()=>{
  const settings={...defaultSettings,meals:[{id:'legacy-meal',name:'Custom lunch',duration_minutes:65,time:'13:35',enabled:false,location_id:'venue'}]}
  const html=renderToStaticMarkup(<SettingsView settings={settings} locations={[{id:'venue',name:'Home kitchen',lat:43,lon:-80,notes:'',travel_overrides:{}}]} busy={false} onSave={()=>{}}/>).split('Meals &amp; recovery')[1]
  expect(html).toContain('Daycraft automatically chooses the meal time')
  expect(html).toContain('value="Custom lunch"')
  expect(html).toContain('value="65"')
  expect(html).toContain('Home kitchen')
  expect(html).toContain('Include meal')
  expect(html).toContain('Remove Custom lunch')
  expect(html).not.toContain('type="time"')
  expect(html).not.toContain('13:35')
  expect(settings.meals[0]).toMatchObject({id:'legacy-meal',time:'13:35',duration_minutes:65})
 })
 it('allows meals to use awake hours outside work and treats disabled meals as absent',()=>{
  const settings={...defaultSettings,wake_time:'07:00',sleep_time:'18:00',work_start:'08:00',work_end:'18:00',meals:[{name:'Breakfast',duration_minutes:30},{name:'Lunch',duration_minutes:45},{name:'Dinner',duration_minutes:30,enabled:false}]}
  expect(estimatedWorkCapacity(plan.date,settings,[])).toBe(585)
  const fixed=[{start:'2032-03-07T07:00:00-05:00',end:'2032-03-07T08:00:00-05:00'}]
  expect(estimatedWorkCapacity(plan.date,settings,fixed)).toBe(525)
 })
})
describe('auditable daily planning',()=>{
 it('distinguishes applied workload from a new selection without changing optimization mode',()=>{
  expect(isPlanStale(plan,'high')).toBe(true)
  const html=renderToStaticMarkup(<><PlanStaleNote schedule={plan} workload="high"/><AppliedWorkload schedule={plan} current="high"/></>)
  expect(html).toContain('Your planning preferences have changed.')
  expect(html).toContain('Applied workload: <strong>Low</strong>')
  expect(html).toContain('Current selection: High; reoptimize to apply it.')
  expect(plan.mode).toBe('deadline')
  expect(isPlanStale(plan,'low')).toBe(false)
  expect(isPlanStale({...plan,preferences_dirty:true},'low')).toBe(true)
 })
 it('does not invent an applied workload for old saved plans',()=>{
  expect(renderToStaticMarkup(<AppliedWorkload schedule={{...plan,workload_level:undefined}} current="medium"/>)).toContain('Workload was not recorded')
 })
 it('renders forecast scope and risks separately from reserved time and confirmed completion',()=>{
  const schedule:Schedule={...plan,horizon_forecast:{start:'2032-03-07',end:'2032-03-20',forecast_only:true,capacity_minutes:120,days:[{date:'2032-03-07',capacity_minutes:120}],task_risks:[{task_definition_id:'task',assignment_id:'week',title:'Prepare assessment',week_start:'2032-03-07',cutoff:'2032-03-09T14:00:00-05:00',remaining_estimated_minutes:180,available_before_cutoff_minutes:120,deadline_risk:'at_risk',reason:'Estimated effort exceeds remaining shared capacity.'}],limitations:['Estimates do not reserve future plans.']}}
  const html=renderToStaticMarkup(<HorizonPanel schedule={schedule}/>)
  expect(html).toContain('2032-03-07 to 2032-03-20')
  expect(html).toContain('Forecast only.')
  expect(html).toContain('Prepare assessment · at risk')
  expect(html).toContain('3h estimated work remaining')
  expect(html).toContain('Estimates do not reserve future plans.')
 })
})
