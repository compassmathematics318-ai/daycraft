import type {Project, ProjectInput, Task} from './types'

export const projectStatuses = ['planning','active','paused','completed','archived'] as const
export const projectCategories = ['academic','software','research','extracurricular','personal','other'] as const
export const titleCase = (value:string) => value.charAt(0).toUpperCase()+value.slice(1)
export const projectInput = (project?:Project):ProjectInput => project ? {
 name:project.name,affiliations:[...project.affiliations],start_date:project.start_date,end_date:project.end_date,
 contributors:project.contributors,importance:project.importance,difficulty:project.difficulty,description:project.description,
 status:project.status,category:project.category,goals:project.goals,links:[...project.links],
} : {name:'',affiliations:[],start_date:null,end_date:null,contributors:1,importance:5,difficulty:5,description:'',status:'active',category:'personal',goals:'',links:[]}
export function linkedProgress(tasks:Task[]) {
 const tracked=tasks.filter(t=>t.status!=='skipped'),completed=tracked.filter(t=>t.status==='completed').length
 return {total:tasks.length,tracked:tracked.length,completed,percent:tracked.length?Math.round(completed/tracked.length*100):null,remaining:tracked.reduce((n,t)=>n+(t.status==='completed'?0:t.remaining_minutes),0)}
}
export function projectValidation(value:ProjectInput):string {
 if(!value.name.trim())return 'Enter a project name.'
 if(value.name.trim().length>200)return 'Project name must be at most 200 characters.'
 if(!Number.isInteger(value.contributors)||value.contributors<1||value.contributors>100000)return 'Contributors must be a whole number from 1 to 100000.'
 if(value.start_date&&value.end_date&&value.end_date<value.start_date)return 'End date cannot precede start date.'
 if(!Number.isFinite(value.importance)||value.importance<1||value.importance>10||value.importance*2%1)return 'Importance must be 1–10 in steps of 0.5.'
 if(!Number.isFinite(value.difficulty)||value.difficulty<0||value.difficulty>10||value.difficulty*2%1)return 'Difficulty must be 0–10 in steps of 0.5.'
 if(value.description.length>20000)return 'Description must be at most 20000 characters.'
 if(value.goals.length>10000)return 'Goals must be at most 10000 characters.'
 if(value.affiliations.length>30||value.affiliations.some(a=>a.length>200))return 'Use at most 30 affiliations, each at most 200 characters.'
 if(value.links.length>30)return 'Use at most 30 relevant links.'
 for(const link of value.links) {try {const url=new URL(link);if(!['http:','https:'].includes(url.protocol)||url.username||url.password||/\s/.test(link)||link.length>2000)return 'Relevant links must be http:// or https:// URLs without credentials or spaces, at most 2000 characters.'} catch {return 'Enter a complete URL for each relevant link.'}}
 return ''
}
