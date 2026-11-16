import {useId} from 'react'
import type {WorkloadLevel} from './types'
import './workloadCompletion.css'

export const workloadLevels:Record<WorkloadLevel,string>={very_low:'Very Low',low:'Low',medium:'Medium',high:'High',very_high:'Very High'}
const workloadDescriptions:Record<WorkloadLevel,string>={very_low:'Immediate obligations and only the most urgent or valuable progress, with generous recovery.',low:'Urgent and high-value tasks with selective additional progress and comfortable breaks.',medium:'Balanced progress across deadlines, weekly responsibilities, and projects, with room to recover.',high:'Substantial useful progress through more productive hours, with deliberate recovery.',very_high:'The broadest useful allocation within your availability, sleep, meals, and recovery needs.'}

export default function WorkloadLevelPicker({value,onChange,disabled=false}:{value:WorkloadLevel;onChange:(value:WorkloadLevel)=>void;disabled?:boolean}) {
 const id=useId()
 return <div className="workload-control"><label htmlFor={id}>Workload Level</label><select id={id} value={value} onChange={event=>onChange(event.target.value as WorkloadLevel)} disabled={disabled} aria-describedby={`${id}-note`}>{Object.entries(workloadLevels).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select><small id={`${id}-note`}>Saved for this date. {workloadDescriptions[value]} Reoptimize to apply changes.</small></div>
}
