import {useEffect,useId,useLayoutEffect,useRef,useState} from 'react'
import type {PointerEvent} from 'react'
import {ArrowDown,ArrowUp,GripVertical,Trash2} from 'lucide-react'
import type {Meal,Place} from './types'
import {mealDropIndex,moveMeal} from './mealOrder'

type Drag={pointerId:number;handle:HTMLButtonElement;from:number;to:number;startY:number;clientY:number;startScrollY:number;y:number;step:number;midpoints:number[];active:boolean}

export default function MealList({meals,locations,onChange}:{meals:Meal[];locations:Place[];onChange:(meals:Meal[])=>void}) {
 const hintId=useId()
 const rows=useRef<(HTMLLIElement|null)[]>([])
 const dragRef=useRef<Drag|null>(null)
 const [drag,setDrag]=useState<Drag|null>(null)
 const [announcement,announce]=useState('')
 const previousRects=useRef<Map<string,number>>(new Map())
 const dragging=Boolean(drag?.active)

 useEffect(()=>{
  if(!dragging)return
  let frame=0
  function tick(){
   const current=dragRef.current
   if(!current?.active)return
   const edge=70
   const speed=current.clientY<edge?-Math.ceil((edge-current.clientY)/edge*12):current.clientY>window.innerHeight-edge?Math.ceil((current.clientY-window.innerHeight+edge)/edge*12):0
   if(speed)window.scrollBy(0,Math.max(-16,Math.min(16,speed)))
   const y=current.clientY-current.startY+window.scrollY-current.startScrollY
   if(y!==current.y){
    const next={...current,y,to:mealDropIndex(current.midpoints,current.midpoints[current.from]+y,current.from)}
    dragRef.current=next
    setDrag(next)
   }
   frame=requestAnimationFrame(tick)
  }
  frame=requestAnimationFrame(tick)
  return()=>cancelAnimationFrame(frame)
 },[dragging])

 useLayoutEffect(()=>{
  const next=new Map<string,number>()
  meals.forEach((meal,index)=>{
   const element=rows.current[index]
   if(!element)return
   const key=meal.id??String(index)
   const top=element.getBoundingClientRect().top+window.scrollY
   const previous=previousRects.current.get(key)
   next.set(key,top)
   if(previous!==undefined&&previous!==top&&!window.matchMedia('(prefers-reduced-motion: reduce)').matches&&element.animate){
    element.animate([{transform:`translateY(${previous-top}px)`},{transform:'translateY(0)'}],{duration:180,easing:'ease-out'})
   }
  })
  previousRects.current=next
 },[meals])

 function reorder(from:number,to:number){
  const next=moveMeal(meals,from,to)
  if(next===meals)return
  previousRects.current=new Map(meals.map((meal,index)=>[meal.id??String(index),(rows.current[index]?.getBoundingClientRect().top??0)+window.scrollY]))
  onChange(next)
  announce(`${meals[from].name} moved to position ${to+1} of ${meals.length}. Save preferences to apply meal order.`)
 }
 function start(e:PointerEvent<HTMLButtonElement>,from:number){
  if(!e.isPrimary||e.button!==0||meals.length<2)return
  // A new gesture must measure settled layout, including after a rapid drop.
  rows.current.forEach(row=>row?.getAnimations().forEach(animation=>animation.finish()))
  const rects=rows.current.slice(0,meals.length).map(row=>row!.getBoundingClientRect())
  const height=rects[from].height
  const gap=rects.length>1?rects[1].top-rects[0].bottom:0
  const value:Drag={pointerId:e.pointerId,handle:e.currentTarget,from,to:from,startY:e.clientY,clientY:e.clientY,startScrollY:window.scrollY,y:0,step:height+gap,midpoints:rects.map(rect=>rect.top+rect.height/2),active:false}
  e.currentTarget.setPointerCapture(e.pointerId)
  e.currentTarget.focus({preventScroll:true})
  dragRef.current=value
  setDrag(value)
 }
 function move(e:PointerEvent<HTMLButtonElement>){
  const current=dragRef.current
  if(!current||current.pointerId!==e.pointerId||current.handle!==e.currentTarget)return
  const y=e.clientY-current.startY+window.scrollY-current.startScrollY
  const active=current.active||Math.abs(y)>4
  const to=active?mealDropIndex(current.midpoints,current.midpoints[current.from]+y,current.from):current.from
  const next={...current,clientY:e.clientY,y,to,active}
  dragRef.current=next
  setDrag(next)
 }
 function finish(e:PointerEvent<HTMLButtonElement>,cancel=false){
  const current=dragRef.current
  if(!current||current.pointerId!==e.pointerId||current.handle!==e.currentTarget)return
  dragRef.current=null
  setDrag(null)
  if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId)
  if(!cancel&&current.active)reorder(current.from,current.to)
  else if(cancel&&current.active)announce('Meal reorder cancelled.')
 }
 function patch(index:number,value:Partial<Meal>){onChange(meals.map((meal,i)=>i===index?{...meal,...value}:meal))}

 return <>
  <p className="meal-order-hint" id={hintId}>Included meals follow this order; Daycraft chooses their times automatically. Drag the grip or use the arrows to set meal order. Save preferences to apply it.</p>
  <ol className={`meal-list ordered-meal-list${drag?.active?' is-reordering':''}`} aria-label="Meal order">
   {meals.map((meal,index)=>{
    const isDragging=Boolean(drag?.active&&drag.from===index)
    const shifted=drag?.active&&index!==drag.from&&((drag.from<index&&index<=drag.to)||(drag.to<=index&&index<drag.from))
    const offset=isDragging?drag!.y:shifted?(drag!.to>drag!.from?-drag!.step:drag!.step):0
    return <li key={meal.id??index} ref={element=>{rows.current[index]=element}} className="meal-order-item" data-meal-id={meal.id??undefined} data-dragging={isDragging||undefined} data-drop-before={Boolean(drag?.active&&drag.to<drag.from&&drag.to===index)||undefined} data-drop-after={Boolean(drag?.active&&drag.to>drag.from&&drag.to===index)||undefined} style={drag?.active?{transform:`translateY(${offset}px)`}:undefined}>
     <div className="meal-order-controls">
      <button type="button" className="icon-button meal-drag-handle" aria-label={`Drag ${meal.name} to reorder`} aria-describedby={hintId} aria-disabled={meals.length<2} onPointerDown={e=>start(e,index)} onPointerMove={move} onPointerUp={e=>finish(e)} onPointerCancel={e=>finish(e,true)} onLostPointerCapture={e=>{if(!e.currentTarget.hasPointerCapture(e.pointerId))finish(e,true)}} onKeyDown={e=>{const current=dragRef.current;if(e.key==='Escape'&&current){e.preventDefault();dragRef.current=null;setDrag(null);if(current.handle.hasPointerCapture(current.pointerId))current.handle.releasePointerCapture(current.pointerId);if(current.active)announce('Meal reorder cancelled.')}}}><GripVertical size={18}/></button>
      <span className="meal-position" aria-hidden="true">{index+1}</span>
      <button type="button" className="icon-button meal-move-button" aria-label={`Move ${meal.name} up`} aria-disabled={index===0} onClick={()=>reorder(index,index-1)}><ArrowUp size={15}/></button>
      <button type="button" className="icon-button meal-move-button" aria-label={`Move ${meal.name} down`} aria-disabled={index===meals.length-1} onClick={()=>reorder(index,index+1)}><ArrowDown size={15}/></button>
     </div>
     <div className="meal-row flexible-meal-row">
      <label className="field"><span>Meal name</span><input required value={meal.name} onChange={e=>patch(index,{name:e.target.value})}/></label>
      <label className="field"><span>Minutes</span><input type="number" required min="5" max="180" step="5" value={meal.duration_minutes} onChange={e=>patch(index,{duration_minutes:+e.target.value})}/></label>
      <label className="field"><span>Meal venue (optional)</span><select value={meal.location_id??''} onChange={e=>patch(index,{location_id:e.target.value||null})}><option value="">Unspecified</option>{locations.map(location=><option key={location.id} value={location.id}>{location.name}</option>)}</select><small>A selected venue reserves travel; otherwise the location stays unspecified.</small></label>
      <label className="check meal-enabled"><input type="checkbox" checked={meal.enabled!==false} onChange={e=>patch(index,{enabled:e.target.checked})}/>Include meal</label>
      <button type="button" className="icon-button danger" aria-label={`Remove ${meal.name}`} onClick={()=>onChange(meals.filter((_,i)=>i!==index))}><Trash2 size={17}/></button>
     </div>
    </li>
   })}
  </ol>
  <p className="meal-order-status" role="status" aria-live="polite" aria-atomic="true">{announcement}</p>
 </>
}
