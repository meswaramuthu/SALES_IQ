import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Users, Briefcase, Activity, CalendarDays, DollarSign, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export default function Dashboard() {
  return (
    <div className="flex flex-col gap-6 pb-12">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Overview</h1>
        <p className="text-muted-foreground mt-2">
          Your AURA agents are actively managing 142 leads and $2.4M in pipeline.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Total Revenue Forecast</CardTitle>
            <DollarSign className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">$2,420,500</div>
            <p className="text-xs text-muted-foreground">+20.1% from last month</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Active Leads</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">+142</div>
            <p className="text-xs text-muted-foreground">Discovery Agent working on 45</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Open Opportunities</CardTitle>
            <Briefcase className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">34</div>
            <p className="text-xs text-muted-foreground">8 require Deal Desk approval</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Upcoming Meetings</CardTitle>
            <CalendarDays className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">12</div>
            <p className="text-xs text-muted-foreground">Booked by Booking Agent</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-7">
        <Card className="col-span-4">
          <CardHeader>
            <CardTitle>Agent Status</CardTitle>
            <CardDescription>Live activity feed from AURA internal agents.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {[
                { name: "Discovery Agent", status: "Active", task: "Scraping 50 domains from LinkedIn", time: "Just now" },
                { name: "Qualification Agent", status: "Active", task: "Scoring MEDDIC for Acme Corp", time: "2 min ago" },
                { name: "Booking Agent", status: "Idle", task: "Waiting for prospect replies", time: "15 min ago" },
                { name: "Proposal Agent", status: "Active", task: "Generating SOW for Globex", time: "1 hr ago" },
                { name: "Deal Desk Agent", status: "Working", task: "Validating 20% discount on 3-year term", time: "3 hrs ago" },
              ].map((agent, i) => (
                <div key={i} className="flex items-center pb-2">
                  <div className="ml-4 space-y-1 w-full">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-medium leading-none flex items-center gap-2">
                        <Activity className={`w-4 h-4 ${agent.status === 'Active' || agent.status === 'Working' ? 'text-green-500 animate-pulse' : 'text-gray-400'}`} />
                        {agent.name}
                      </p>
                      <Badge variant="outline" className={agent.status === 'Active' || agent.status === 'Working' ? 'text-green-500 border-green-500/20 bg-green-500/10' : ''}>
                        {agent.status}
                      </Badge>
                    </div>
                    <div className="flex items-center justify-between mt-1">
                      <p className="text-sm text-muted-foreground">{agent.task}</p>
                      <span className="text-xs text-muted-foreground">{agent.time}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        
        <Card className="col-span-3">
          <CardHeader>
            <CardTitle>Pipeline Velocity</CardTitle>
            <CardDescription>Average time spent in each stage.</CardDescription>
          </CardHeader>
          <CardContent className="h-[300px] flex items-center justify-center text-muted-foreground border-t border-border mt-4 pt-4">
            <div className="flex flex-col items-center gap-4">
              <TrendingUp className="w-12 h-12 text-primary opacity-50" />
              <p>Pipeline visualization component coming soon.</p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
