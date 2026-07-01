import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const stages = ["Discovery", "Qualification", "Proposal", "Negotiation", "Closed Won"];

const opportunities = [
  { id: 1, title: "Acme Corp - Enterprise License", amount: 120000, stage: "Negotiation", assignee: "Jane Doe" },
  { id: 2, title: "Globex Inc - Implementation", amount: 45000, stage: "Proposal", assignee: "John Smith" },
  { id: 3, title: "Soylent - 50 Seats", amount: 25000, stage: "Qualification", assignee: "Jane Doe" },
  { id: 4, title: "Massive Dynamic - Platform", amount: 350000, stage: "Discovery", assignee: "Alex Johnson" },
  { id: 5, title: "Initech - Expansion", amount: 80000, stage: "Closed Won", assignee: "John Smith" },
];

export default function Opportunities() {
  return (
    <div className="flex flex-col gap-6 pb-12 h-full">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Opportunities</h1>
        <p className="text-muted-foreground mt-2">
          Track deals across stages.
        </p>
      </div>

      <div className="flex gap-4 overflow-x-auto pb-4 flex-1">
        {stages.map((stage) => {
          const stageOpps = opportunities.filter((opp) => opp.stage === stage);
          const totalAmount = stageOpps.reduce((sum, opp) => sum + opp.amount, 0);
          
          return (
            <div key={stage} className="min-w-[300px] flex flex-col gap-3">
              <div className="flex items-center justify-between mb-2">
                <h3 className="font-semibold">{stage}</h3>
                <Badge variant="secondary">{stageOpps.length}</Badge>
              </div>
              <div className="text-sm text-muted-foreground font-medium mb-2">
                ${totalAmount.toLocaleString()}
              </div>
              
              <div className="flex flex-col gap-3">
                {stageOpps.map((opp) => (
                  <Card key={opp.id} className="cursor-pointer hover:border-primary transition-colors">
                    <CardHeader className="p-4 pb-2">
                      <CardTitle className="text-sm">{opp.title}</CardTitle>
                    </CardHeader>
                    <CardContent className="p-4 pt-0">
                      <div className="flex items-center justify-between mt-2">
                        <span className="text-sm font-bold text-primary">
                          ${opp.amount.toLocaleString()}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {opp.assignee}
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
