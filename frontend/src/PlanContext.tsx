import {AlertCircle,Target} from 'lucide-react'
import type {Schedule,WorkloadLevel} from './types'
import {workloadLevels} from './WorkloadLevel'
import {duration,localDate,time} from './utils'
import './intelligentPlanning.css'

export function isPlanStale(schedule:Schedule,workload:WorkloadLevel){return !!(schedule.needs_regeneration||schedule.preferences_dirty||schedule.calendar_dirty||schedule.projects_dirty||schedule.tasks_dirty||schedule.locations_dirty||(schedule.workload_level&&schedule.workload_level!==workload))}
export function PlanStaleNote({schedule,workload}:{schedule?:Schedule;workload:WorkloadLevel}){
 if(!schedule||!isPlanStale(schedule,workload))return null
 const reason=schedule.preferences_dirty||schedule.workload_level&&schedule.workload_level!==workload?'Your planning preferences have changed.':schedule.locations_dirty?'Your saved plan needs location review.':schedule.tasks_dirty?'Your tasks have changed.':schedule.projects_dirty?'Your project context has changed.':schedule.calendar_dirty?'Your calendar has changed.':'Your saved plan needs regeneration.'
 return <div className="calendar-stale-note" role="status"><AlertCircle size={18}/><span><strong>{reason}</strong> Reoptimize this day to use the latest preferences, calendar, tasks, projects, and authorized locations. Completed and started work stays in place.</span></div>
}
export function AppliedWorkload({schedule,current}:{schedule:Schedule;current:WorkloadLevel}){
 return <p className="applied-workload">{schedule.workload_level?<>Applied workload: <strong>{workloadLevels[schedule.workload_level]}</strong>.{schedule.workload_level!==current&&<> Current selection: {workloadLevels[current]}; reoptimize to apply it.</>}</>:<>Workload was not recorded for this saved plan. Reoptimize to apply {workloadLevels[current]}.</>}</p>
}
export function HorizonPanel({schedule,timezone='America/Toronto'}:{schedule:Schedule;timezone?:string}){
 const forecast=schedule.horizon_forecast
 if(!forecast)return null
 const risks=forecast.task_risks.filter(item=>item.deadline_risk!=='none')
 return <section className="panel forecast-panel"><div className="section-heading"><h2><Target size={18}/> Horizon forecast</h2></div><p className="forecast-scope">{forecast.start} to {forecast.end} · {duration(forecast.capacity_minutes)} estimated capacity across {forecast.days.length} days.</p><p>Forecast only. Future days are estimates; this does not reserve time or confirm completed work.</p>{risks.length>0&&<div className="unallocated-list">{risks.map(item=><div key={`${item.assignment_id}-${item.week_start}`}><strong>{item.title} · {item.deadline_risk.replaceAll('_',' ')}</strong><span>{duration(item.remaining_estimated_minutes)} estimated work remaining{item.cutoff?` · cutoff ${localDate(new Date(item.cutoff),timezone)} at ${time(item.cutoff,timezone)}`:''}</span><p>{item.reason}</p></div>)}</div>}{forecast.limitations.length>0&&<ul>{forecast.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul>}</section>
}
