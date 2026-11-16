import type {Block} from './types'

export function isTaskWorkBlock(block:Block):boolean {
 return (block.kind==='task'||block.kind==='project')&&!!(block.task_definition_id||block.task_id)
}

export function isSessionCompleted(block:Block):boolean {
 return isTaskWorkBlock(block)&&block.status==='completed'
}

export function canCompleteSession(block:Block,now=Date.now()):boolean {
 return isTaskWorkBlock(block)&&Number.isFinite(Date.parse(block.end))&&Date.parse(block.end)<=now
}
