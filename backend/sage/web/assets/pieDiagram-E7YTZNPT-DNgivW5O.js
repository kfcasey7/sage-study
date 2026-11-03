import{p as at}from"./chunk-JWPE2WC7-WQbrEoQ-.js";import{g as nt,s as rt,a as it,b as ot,o as st,n as lt,_ as g,l as G,c as ct,A as ut,D as dt,M as gt,d as pt,p as ht,B as ft}from"./mermaid.core-CqscAVdN.js";import{p as mt}from"./cynefin-OW5HDTMX-DuF5Fq9i.js";import{d as q}from"./arc-ByXL-oaN.js";import{x as T,t as B,aa as vt,ab as xt}from"./index-FOnpRLea.js";function St(t,r){return r<t?-1:r>t?1:r>=t?0:NaN}function yt(t){return t}function wt(){var t=yt,r=St,y=null,b=T(0),l=T(B),p=T(0);function i(e){var n,s=(e=vt(e)).length,h,w,$=0,f=new Array(s),o=new Array(s),D=+b.apply(this,arguments),z=Math.min(B,Math.max(-B,l.apply(this,arguments)-D)),k,L=Math.min(Math.abs(z)/s,p.apply(this,arguments)),u=L*(z<0?-1:1),A;for(n=0;n<s;++n)(A=o[f[n]=n]=+t(e[n],n,e))>0&&($+=A);for(r!=null?f.sort(function(E,m){return r(o[E],o[m])}):y!=null&&f.sort(function(E,m){return y(e[E],e[m])}),n=0,w=$?(z-s*u)/$:0;n<s;++n,D=k)h=f[n],A=o[h],k=D+(A>0?A*w:0)+u,o[h]={data:e[h],index:n,value:A,startAngle:D,endAngle:k,padAngle:L};return o}return i.value=function(e){return arguments.length?(t=typeof e=="function"?e:T(+e),i):t},i.sortValues=function(e){return arguments.length?(r=e,y=null,i):r},i.sort=function(e){return arguments.length?(y=e,r=null,i):y},i.startAngle=function(e){return arguments.length?(b=typeof e=="function"?e:T(+e),i):b},i.endAngle=function(e){return arguments.length?(l=typeof e=="function"?e:T(+e),i):l},i.padAngle=function(e){return arguments.length?(p=typeof e=="function"?e:T(+e),i):p},i}var At=ft.pie,I={sections:new Map,showData:!1},F=I.sections,V=I.showData,Ct=structuredClone(At),$t=g(()=>structuredClone(Ct),"getConfig"),Dt=g(()=>{F=new Map,V=I.showData,ht()},"clear"),Tt=g(({label:t,value:r})=>{if(r<0)throw new Error(`"${t}" has invalid value: ${r}. Negative values are not allowed in pie charts. All slice values must be >= 0.`);F.has(t)||(F.set(t,r),G.debug(`added new section: ${t}, with value: ${r}`))},"addSection"),bt=g(()=>F,"getSections"),kt=g(t=>{V=t},"setShowData"),Mt=g(()=>V,"getShowData"),J={getConfig:$t,clear:Dt,setDiagramTitle:lt,getDiagramTitle:st,setAccTitle:ot,getAccTitle:it,setAccDescription:rt,getAccDescription:nt,addSection:Tt,getSections:bt,setShowData:kt,getShowData:Mt},zt=g((t,r)=>{at(t,r),r.setShowData(t.showData),t.sections.map(r.addSection)},"populateDb"),Et={parse:g(async t=>{const r=await mt("pie",t);G.debug(r),zt(r,J)},"parse")},Rt=g(t=>`
  .pieCircle{
    stroke: ${t.pieStrokeColor};
    stroke-width : ${t.pieStrokeWidth};
    opacity : ${t.pieOpacity};
  }
  .pieCircle.highlighted{
    scale: 1.05;
    opacity: 1;
  }
  .pieCircle.highlightedOnHover:hover{
    transition-duration: 250ms;
    scale: 1.05;
    opacity: 1;
  }
  .pieOuterCircle{
    stroke: ${t.pieOuterStrokeColor};
    stroke-width: ${t.pieOuterStrokeWidth};
    fill: none;
  }
  .pieTitleText {
    text-anchor: middle;
    font-size: ${t.pieTitleTextSize};
    fill: ${t.pieTitleTextColor};
    font-family: ${t.fontFamily};
  }
  .slice {
    font-family: ${t.fontFamily};
    fill: ${t.pieSectionTextColor};
    font-size:${t.pieSectionTextSize};
    // fill: white;
  }
  .legend text {
    fill: ${t.pieLegendTextColor};
    font-family: ${t.fontFamily};
    font-size: ${t.pieLegendTextSize};
  }
`,"getStyles"),Lt=Rt,Wt=g(t=>{const r=[...t.values()].reduce((l,p)=>l+p,0),y=[...t.entries()].map(([l,p])=>({label:l,value:p})).filter(l=>l.value/r*100>=1);return wt().value(l=>l.value).sort(null)(y)},"createPieArcs"),_t=g((t,r,y,b)=>{G.debug(`rendering pie chart
`+t);const l=b.db,p=ct(),i=ut(l.getConfig(),p.pie),e=40,n=18,s=4,h=450,w=h,$=dt(r),f=$.append("g");f.attr("transform","translate("+w/2+","+h/2+")");const{themeVariables:o}=p;let[D]=gt(o.pieOuterStrokeWidth);D??=2;const z=i.legendPosition,k=i.textPosition,L=i.donutHole>0&&i.donutHole<=.9?i.donutHole:0,u=Math.min(w,h)/2-e,A=q().innerRadius(L*u).outerRadius(u),E=q().innerRadius(u*k).outerRadius(u*k),m=f.append("g");m.append("circle").attr("cx",0).attr("cy",0).attr("r",u+D/2).attr("class","pieOuterCircle");const W=l.getSections(),K=Wt(W),Q=[o.pie1,o.pie2,o.pie3,o.pie4,o.pie5,o.pie6,o.pie7,o.pie8,o.pie9,o.pie10,o.pie11,o.pie12];let H=0;W.forEach(a=>{H+=a});const U=K.filter(a=>(a.data.value/H*100).toFixed(0)!=="0"),N=xt(Q).domain([...W.keys()]);m.selectAll("mySlices").data(U).enter().append("path").attr("d",A).attr("fill",a=>N(a.data.label)).attr("class",a=>{let c="pieCircle";return i.highlightSlice==="hover"?c+=" highlightedOnHover":i.highlightSlice===a.data.label&&(c+=" highlighted"),c}),m.selectAll("mySlices").data(U).enter().append("text").text(a=>(a.data.value/H*100).toFixed(0)+"%").attr("transform",a=>"translate("+E.centroid(a)+")").style("text-anchor","middle").attr("class","slice");const Y=f.append("text").text(l.getDiagramTitle()).attr("x",0).attr("y",-400/2).attr("class","pieTitleText"),R=[...W.entries()].map(([a,c])=>({label:a,value:c})),C=f.selectAll(".legend").data(R).enter().append("g").attr("class","legend");C.append("rect").attr("width",n).attr("height",n).style("fill",a=>N(a.label)).style("stroke",a=>N(a.label)),C.append("text").attr("x",n+s).attr("y",n-s).text(a=>l.getShowData()?`${a.label} [${a.value}]`:a.label);const M=Math.max(...C.selectAll("text").nodes().map(a=>a?.getBoundingClientRect().width??0));let _=h,O=w+e;const d=n+s,P=R.length*d;switch(z){case"center":C.attr("transform",(a,c)=>{const v=d*R.length/2,x=-M/2-(n+s),S=c*d-v;return"translate("+x+","+S+")"});break;case"top":_+=P,C.attr("transform",(a,c)=>{const v=u,x=-M/2-(n+s),S=c*d-v;return`translate(${x}, ${S})`}),m.attr("transform",()=>`translate(0, ${P+d})`);break;case"bottom":_+=P,C.attr("transform",(a,c)=>{const v=-u-d,x=-M/2-(n+s),S=c*d-v;return"translate("+x+","+S+")"});break;case"left":O+=n+s+M,C.attr("transform",(a,c)=>{const v=d*R.length/2,x=-u-(n+s),S=c*d-v;return"translate("+x+","+S+")"}),m.attr("transform",()=>`translate(${M+n+s}, 0)`);break;case"right":default:O+=n+s+M,C.attr("transform",(a,c)=>{const v=d*R.length/2,x=12*n,S=c*d-v;return"translate("+x+","+S+")"});break}const j=Y.node()?.getBoundingClientRect().width??0,tt=w/2-j/2,et=w/2+j/2,X=Math.min(0,tt),Z=Math.max(O,et)-X;$.attr("viewBox",`${X} 0 ${Z} ${_}`),pt($,_,Z,i.useMaxWidth)},"draw"),Ft={draw:_t},It={parser:Et,db:J,renderer:Ft,styles:Lt};export{It as diagram};
