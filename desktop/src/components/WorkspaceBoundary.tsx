import {Component,type ReactNode} from 'react';

/** Recover the workspace without clearing persisted drafts or backend jobs. */
export default class WorkspaceBoundary extends Component<{children:ReactNode},{failed:boolean}>{
  state={failed:false};
  static getDerivedStateFromError(){return{failed:true};}
  componentDidCatch(error:Error){console.error('Workspace view failed',error);}
  render(){
    if(this.state.failed)return <main className="detail-body"><section className="panel detail-body" role="alert"><h1>This view could not load</h1><p>Your saved scripts, uploads and running jobs are preserved. Reload the workspace to reconnect.</p><button className="button primary" onClick={()=>window.location.reload()}>Reload workspace</button></section></main>;
    return this.props.children;
  }
}
