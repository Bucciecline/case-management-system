#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, itertools, json, urllib.request
from pathlib import Path
import numpy as np
import pandas as pd

DOMAINS=("elo","offense","defense","net","schedule_strength","prior_win_pct","prior_point_diff")
YEARS=(2021,2022,2023,2024,2025)
OUT=Path("alphaodds/winner_dna/outputs/minimum_core")
RAW=Path("winner_dna_minimum_core_runtime")
OUT.mkdir(parents=True,exist_ok=True); RAW.mkdir(parents=True,exist_ok=True)
FROZEN={"n":176,"wins":134,"accuracy":134/176}

def load_control_module():
    p=Path("alphaodds/winner_dna/qb_first_gate.py")
    s=importlib.util.spec_from_file_location("winner_dna_control",p)
    if s is None or s.loader is None: raise RuntimeError("cannot load frozen Winner DNA control")
    m=importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def schedule(mod):
    p=RAW/"games.csv"
    req=urllib.request.Request("https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv",headers={"User-Agent":"AlphaNFL-MinimumCore/1.0"})
    with urllib.request.urlopen(req,timeout=240) as r,p.open("wb") as w:
        while True:
            b=r.read(1<<20)
            if not b: break
            w.write(b)
    d=pd.read_csv(p,low_memory=False)
    d=d[d.season.isin(range(2019,2026))].copy()
    d=d[d.game_type.astype(str).str.upper().isin(["REG","WC","DIV","CON","SB","POST"])].copy()
    d["gameday"]=pd.to_datetime(d.gameday,errors="coerce")
    d["home_team"]=d.home_team.map(mod.ct); d["away_team"]=d.away_team.map(mod.ct)
    for c in ["home_score","away_score","week"]: d[c]=pd.to_numeric(d[c],errors="coerce")
    return d[d.home_score.notna()&d.away_score.notna()].sort_values(["gameday","game_id"],kind="mergesort").reset_index(drop=True)

def subset_unanimity(g, subset):
    cols=[f"vote_{x}" for x in subset]
    d=g[g.winner.notna()].copy()
    complete=d[cols].notna().all(axis=1)
    d=d[complete].copy()
    first=d[cols[0]]
    un=pd.Series(True,index=d.index)
    for c in cols[1:]: un &= d[c].eq(first)
    u=d[un].copy()
    u["subset_pick"]=u[cols[0]]
    overall={"n_complete":int(len(d)),"n_unanimous":int(len(u)),"wins":int((u.subset_pick==u.winner).sum()),
             "accuracy":float((u.subset_pick==u.winner).mean()) if len(u) else None,
             "unanimous_rate":float(len(u)/len(d)) if len(d) else None}
    by={}
    for y in YEARS:
        z=u[u.season.eq(y)]
        by[str(y)]={"n":int(len(z)),"wins":int((z.subset_pick==z.winner).sum()),
                    "accuracy":float((z.subset_pick==z.winner).mean()) if len(z) else None}
    eval_years=[v for v in by.values() if v["n"]>=10 and v["accuracy"] is not None]
    stable={"years_n_ge_10":len(eval_years),
            "years_above_50pct":sum(v["accuracy"]>.5 for v in eval_years),
            "years_at_or_above_60pct":sum(v["accuracy"]>=.60 for v in eval_years),
            "min_accuracy_evaluated":min((v["accuracy"] for v in eval_years),default=None),
            "cross_season_positive":bool(len(eval_years)>=4 and sum(v["accuracy"]>.5 for v in eval_years)>=4)}
    return overall,by,stable,u

def leave_one_out(g, omitted):
    subset=tuple(x for x in DOMAINS if x!=omitted)
    overall,by,stable,u=subset_unanimity(g,subset)
    oc=f"vote_{omitted}"
    z=u[u[oc].notna()].copy()
    z["omitted_agrees"]=z[oc].eq(z.subset_pick)
    agree=z[z.omitted_agrees]; disagree=z[~z.omitted_agrees]
    # If omitted domain disagrees, six-domain pick accuracy <50% implies omitted domain was a useful protective veto.
    veto={"subset":list(subset),"six_core":overall,
          "omitted_present_n":int(len(z)),
          "omitted_agrees_n":int(len(agree)),
          "omitted_disagrees_n":int(len(disagree)),
          "six_core_accuracy_when_omitted_agrees":float((agree.subset_pick==agree.winner).mean()) if len(agree) else None,
          "six_core_accuracy_when_omitted_disagrees":float((disagree.subset_pick==disagree.winner).mean()) if len(disagree) else None,
          "omitted_domain_accuracy_when_disagrees":float((disagree[oc]==disagree.winner).mean()) if len(disagree) else None,
          "protective_veto_signal":None}
    if len(disagree)>=10:
        a=veto["six_core_accuracy_when_omitted_disagrees"]
        veto["protective_veto_signal"]="PROTECTIVE" if a<.5 else ("REDUNDANT_OR_HARMFUL_VETO" if a>.5 else "NEUTRAL")
    else: veto["protective_veto_signal"]="LOW_SAMPLE"
    per={}
    for y in YEARS:
        q=disagree[disagree.season.eq(y)]
        per[str(y)]={"n":int(len(q)),"six_core_wins":int((q.subset_pick==q.winner).sum()),
                     "six_core_accuracy":float((q.subset_pick==q.winner).mean()) if len(q) else None}
    veto["disagreement_by_season"]=per
    return veto

def pairwise(g):
    rows=[]
    for a,b in itertools.combinations(DOMAINS,2):
        ca,cb=f"vote_{a}",f"vote_{b}"
        x=g[g.winner.notna()&g[ca].notna()&g[cb].notna()].copy()
        dis=x[x[ca]!=x[cb]]
        rows.append({"domain_a":a,"domain_b":b,"n":int(len(x)),
                     "agreement_rate":float((x[ca]==x[cb]).mean()) if len(x) else None,
                     "disagreement_n":int(len(dis)),
                     "a_accuracy_when_disagree":float((dis[ca]==dis.winner).mean()) if len(dis) else None,
                     "b_accuracy_when_disagree":float((dis[cb]==dis.winner).mean()) if len(dis) else None})
    return pd.DataFrame(rows)

def main():
    mod=load_control_module()
    s=schedule(mod); g=mod.control(s); g=g[g.season.isin(YEARS)&g.winner.notna()].copy()
    cm=mod.control_summary(g); rc=mod.recon(cm)
    results=[]; season_rows=[]; unanimous_frames={}
    for k in (6,5,4):
        for subset in itertools.combinations(DOMAINS,k):
            o,by,st,u=subset_unanimity(g,subset)
            key="+".join(subset)
            results.append({"size":k,"subset":key,**o,**st})
            for y,v in by.items(): season_rows.append({"size":k,"subset":key,"season":int(y),**v})
            unanimous_frames[key]=u[["game_id","season","winner","subset_pick"]].copy()
    res=pd.DataFrame(results)
    seasons=pd.DataFrame(season_rows)
    loo=[{"omitted":d,**leave_one_out(g,d)} for d in DOMAINS]
    loo_flat=[]
    for x in loo:
        six=x["six_core"]
        loo_flat.append({"omitted":x["omitted"],"six_subset":"+".join(x["subset"]),
                         "six_unanimous_n":six["n_unanimous"],"six_wins":six["wins"],"six_accuracy":six["accuracy"],
                         "omitted_present_n":x["omitted_present_n"],"omitted_agrees_n":x["omitted_agrees_n"],
                         "omitted_disagrees_n":x["omitted_disagrees_n"],
                         "six_core_accuracy_when_omitted_agrees":x["six_core_accuracy_when_omitted_agrees"],
                         "six_core_accuracy_when_omitted_disagrees":x["six_core_accuracy_when_omitted_disagrees"],
                         "omitted_domain_accuracy_when_disagrees":x["omitted_domain_accuracy_when_disagrees"],
                         "protective_veto_signal":x["protective_veto_signal"]})
    loo_df=pd.DataFrame(loo_flat)

    # Descriptive Pareto frontier only: accuracy versus unanimous sample size.
    valid=res[res.accuracy.notna()&res.n_unanimous.gt(0)].copy()
    frontier=[]
    for i,r in valid.iterrows():
        dominated=((valid.accuracy>=r.accuracy)&(valid.n_unanimous>=r.n_unanimous)&
                   ((valid.accuracy>r.accuracy)|(valid.n_unanimous>r.n_unanimous))).any()
        if not dominated: frontier.append(r.to_dict())
    frontier=sorted(frontier,key=lambda x:(x["size"],-x["accuracy"],-x["n_unanimous"]))

    # Smallest stable descriptive cores: cross-season positive, >=100 unanimous games, no evaluated year below 50%.
    candidates=valid[(valid.cross_season_positive==True)&(valid.n_unanimous>=100)].copy()
    candidates=candidates.sort_values(["size","accuracy","n_unanimous"],ascending=[True,False,False])
    min_size=int(candidates["size"].min()) if len(candidates) else None
    smallest=candidates[candidates["size"].eq(min_size)].head(10).to_dict("records") if min_size else []

    # Domain prevalence across top descriptive subsets, not a selection rule.
    top=valid.sort_values(["accuracy","n_unanimous"],ascending=[False,False]).head(15)
    freq={d:int(top["subset"].str.split("+").apply(lambda xs:d in xs).sum()) for d in DOMAINS}

    report={
      "gate":"ALPHANFL WINNER DNA — INFORMATION REDUNDANCY / MINIMUM WINNING DNA",
      "status":"PASS_RETROSPECTIVE_DIAGNOSTIC_NO_PROMOTION" if rc["status"].startswith("PASS") else "PARTIAL_HOLD_RECONSTRUCTION",
      "frozen_reference":FROZEN,
      "reconstructed_control":cm,
      "reconstruction_check":rc,
      "design":{
        "domains":list(DOMAINS),
        "subset_sizes":[6,5,4],
        "subsets_tested":int(len(res)),
        "signal":"all selected domains must be present and unanimous; no learned weights",
        "stability_rule":"descriptive cross-season positive = at least 4 seasons with n>=10 and accuracy>50%; not a promotion rule",
        "leave_one_out_veto_rule":"if six-domain unanimous pick is below 50% when omitted domain disagrees, omitted domain is descriptively protective",
        "multiple_comparison_control":"no retrospective subset may replace Winner DNA v1 from this gate; any candidate requires a separately frozen prospective/untouched holdout test"},
      "leave_one_out":loo,
      "pareto_frontier":frontier,
      "smallest_cross_season_positive_candidates":smallest,
      "top15_domain_frequency":freq,
      "cca15":{
        "winner_dna_v1_mutation":"NONE",
        "qb_or_other_challenger_use":"NONE",
        "posthoc_weighting":"NONE",
        "posthoc_threshold_tuning":"NONE",
        "all_4_5_6_subsets_exhaustively_tested":True,
        "multiple_comparison_promotion":"PROHIBITED",
        "profitability_claim":"PROHIBITED",
        "wager_execution":"DISABLED"},
      "defense_red_team":{
        "reconstruction_not_identical_to_frozen_reference":"YES_FROZEN_176_134_REMAINS_AUTHORITY",
        "subset_search_bias":"MATERIAL_63_SUBSETS_TESTED",
        "sample_size_tradeoff":"SMALLER_CORES_CREATE_MORE_SIGNALS_BUT_CAN_LOWER_ACCURACY",
        "domain_collinearity":"EXPECTED_OFFENSE_NET_PRIOR_RECORD_POINT_DIFF_ARE_CORRELATED",
        "schedule_strength_low_standalone_accuracy":"DOES_NOT_IMPLY_NO_INCREMENTAL_VETO_VALUE",
        "decision":"NO_AUTOMATIC_CORE_REPLACEMENT"}
    }
    res.to_csv(OUT/"SUBSET_UNANIMITY_RESULTS.csv",index=False)
    seasons.to_csv(OUT/"SUBSET_YEAR_BY_YEAR.csv",index=False)
    loo_df.to_csv(OUT/"LEAVE_ONE_OUT_VETO_AUDIT.csv",index=False)
    pairwise(g).to_csv(OUT/"PAIRWISE_DOMAIN_REDUNDANCY.csv",index=False)
    pd.DataFrame(frontier).to_csv(OUT/"PARETO_FRONTIER.csv",index=False)
    (OUT/"MINIMUM_WINNING_DNA_GATE.json").write_text(json.dumps(report,indent=2,default=str),encoding="utf-8")
    md=["# ALPHANFL WINNER DNA — INFORMATION REDUNDANCY / MINIMUM WINNING DNA","",
        f"Status: **{report['status']}**","",
        f"Subsets tested: {len(res)} (7 six-domain, 21 five-domain, 35 four-domain).","",
        "## Leave-one-out veto audit"]
    for x in loo_flat:
        md.append(f"- Omit {x['omitted']}: six-core {x['six_wins']}/{x['six_unanimous_n']} = {x['six_accuracy']:.3f}; omitted disagrees N={x['omitted_disagrees_n']}, six-core accuracy there={x['six_core_accuracy_when_omitted_disagrees']}; signal={x['protective_veto_signal']}")
    md += ["","## Smallest cross-season-positive descriptive candidates",json.dumps(smallest,indent=2,default=str),
           "","## CCA15",json.dumps(report["cca15"],indent=2),"","## Defense Red Team",json.dumps(report["defense_red_team"],indent=2)]
    (OUT/"MINIMUM_WINNING_DNA_GATE.md").write_text("\n".join(md)+"\n",encoding="utf-8")
    print("MINIMUM_CORE_REPORT_BEGIN"); print(json.dumps(report,indent=2,default=str)); print("MINIMUM_CORE_REPORT_END")

if __name__=="__main__":
    main()
