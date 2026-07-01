import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Activity, Bot, MessageSquare, CheckCircle2, Clock, AlertCircle } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";

const agents = [
  { name: "Discovery Agent", status: "Active", tasks: 45, type: "Prospecting" },
  { name: "Qualification Agent", status: "Active", tasks: 12, type: "Scoring" },
  { name: "Booking Agent", status: "Idle", tasks: 0, type: "Scheduling" },
  { name: "Proposal Agent", status: "Active", tasks: 3, type: "Document Generation" },
  { name: "Followup Agent", status: "Working", tasks: 156, type: "Outreach" },
  { name: "Revenue Agent", status: "Idle", tasks: 0, type: "Analysis" },
  { name: "Deal Desk Agent", status: "Working", tasks: 8, type: "Validation" },
];

const timeline = [
  { time: "10:45 AM", agent: "Deal Desk Agent", action: "Approved 15% discount for Acme Corp", status: "success" },
  { time: "10:42 AM", agent: "Qualification Agent", action: "Updated MEDDIC score for Globex to 92", status: "info" },
  { time: "10:30 AM", agent: "Followup Agent", action: "Sent 45 automated check-in emails", status: "success" },
  { time: "10:15 AM", agent: "Discovery Agent", action: "Found 12 new VP Engineering leads at Series B startups", status: "info" },
  { time: "09:55 AM", agent: "Proposal Agent", action: "Failed to generate PDF for Initech due to missing pricing tier", status: "error" },
  { time: "09:50 AM", agent: "Revenue Agent", action: "Recalculated pipeline velocity: +12% week-over-week", status: "info" },
  { time: "09:15 AM", agent: "Booking Agent", action: "Scheduled 3 meetings for Next Week", status: "success" },
];

export default function AgentActivity() {
  return (
    <div className="flex flex-col gap-6 pb-12 h-full">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Agent Activity</h1>
        <p className="text-muted-foreground mt-2">
          Monitor your AURA swarm in real-time.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-3 h-[calc(100vh-12rem)]">
        <Card className="col-span-1 flex flex-col">
          <CardHeader>
            <CardTitle>System Status</CardTitle>
            <CardDescription>Live health and queue of all agents.</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 overflow-hidden">
            <ScrollArea className="h-full pr-4">
              <div className="flex flex-col gap-4">
                {agents.map((agent) => (
                  <div key={agent.name} className="flex flex-col gap-2 p-3 rounded-lg border border-border bg-muted/20">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2 font-medium">
                        <Bot className="w-4 h-4 text-primary" />
                        {agent.name}
                      </div>
                      <Badge variant="outline" className={
                        agent.status === 'Active' || agent.status === 'Working' 
                          ? 'text-green-500 border-green-500/20 bg-green-500/10' 
                          : 'text-gray-500 border-gray-500/20 bg-gray-500/10'
                      }>
                        {agent.status === 'Active' && <Activity className="w-3 h-3 mr-1 animate-pulse" />}
                        {agent.status}
                      </Badge>
                    </div>
                    <div className="flex items-center justify-between text-sm text-muted-foreground">
                      <span>{agent.type}</span>
                      <span className="flex items-center gap-1">
                        <MessageSquare className="w-3 h-3" />
                        {agent.tasks} tasks in queue
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>

        <Card className="col-span-2 flex flex-col">
          <CardHeader>
            <CardTitle>Conversation & Action Timeline</CardTitle>
            <CardDescription>Chronological log of all autonomous agent actions.</CardDescription>
          </CardHeader>
          <CardContent className="flex-1 overflow-hidden">
            <ScrollArea className="h-full pr-4">
              <div className="relative pl-6 border-l-2 border-border/50 ml-3 space-y-8 pb-4">
                {timeline.map((event, i) => (
                  <div key={i} className="relative">
                    <div className="absolute -left-[35px] top-1 bg-background p-1 rounded-full border border-border">
                      {event.status === 'success' ? <CheckCircle2 className="w-4 h-4 text-green-500" /> :
                       event.status === 'error' ? <AlertCircle className="w-4 h-4 text-red-500" /> :
                       <Activity className="w-4 h-4 text-blue-500" />}
                    </div>
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Clock className="w-3 h-3" />
                        {event.time}
                        <span className="mx-1">•</span>
                        <span className="font-medium text-foreground">{event.agent}</span>
                      </div>
                      <p className={`text-sm ${event.status === 'error' ? 'text-red-400' : 'text-card-foreground'}`}>
                        {event.action}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
