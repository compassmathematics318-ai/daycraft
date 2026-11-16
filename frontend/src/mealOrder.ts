import type {Meal} from './types'

// Preserve the original objects, including retained fields such as legacy time.
export function moveMeal(meals:Meal[],from:number,to:number):Meal[] {
 if(!Number.isInteger(from)||!Number.isInteger(to)||from<0||to<0||from>=meals.length||to>=meals.length||from===to)return meals
 const next=[...meals]
 const [meal]=next.splice(from,1)
 next.splice(to,0,meal)
 return next
}

export function mealDropIndex(midpoints:number[],pointerY:number,from:number):number {
 let target=from
 while(target>0&&pointerY<midpoints[target-1])target--
 while(target<midpoints.length-1&&pointerY>midpoints[target+1])target++
 return target
}
