import type {Settings} from './types'
import {availableMinutes,localIso,nextDate} from './utils'

// Flexible meals may use free awake time outside working hours. This is a
// capacity estimate only: meal timing, fragmentation, routes and recovery are
// resolved by generation, rather than inventing meal appointments here.
export function estimatedWorkCapacity(date:string,settings:Settings,fixed:{start:string;end:string}[]){
 const at=(clock:string)=>localIso(`${date}T${clock}`,settings.timezone)
 const wake=at(settings.wake_time),sleep=localIso(`${settings.sleep_time<=settings.wake_time?nextDate(date,1):date}T${settings.sleep_time}`,settings.timezone)
 const workStart=new Date(Math.max(Date.parse(wake),Date.parse(at(settings.work_start)))).toISOString()
 const workEnd=new Date(Math.min(Date.parse(sleep),Date.parse(at(settings.work_end)))).toISOString()
 const workFree=availableMinutes(workStart,workEnd,fixed),awakeFree=availableMinutes(wake,sleep,fixed)
 const meals=settings.meals.filter(meal=>meal.enabled!==false).reduce((total,meal)=>total+meal.duration_minutes,0)
 return Math.max(0,workFree-Math.max(0,meals-Math.max(0,awakeFree-workFree)))
}
