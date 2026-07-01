import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

const leads = [
  { id: 1, company: "Acme Corp", contact: "John Doe", title: "VP Engineering", industry: "SaaS", score: 85, status: "Qualified" },
  { id: 2, company: "Globex Inc", contact: "Jane Smith", title: "CTO", industry: "Fintech", score: 92, status: "Qualified" },
  { id: 3, company: "Initech", contact: "Bill Lumbergh", title: "Division Manager", industry: "Enterprise", score: 45, status: "Cold" },
  { id: 4, company: "Soylent", contact: "Robert Paulson", title: "VP Product", industry: "Food Tech", score: 78, status: "Warm" },
  { id: 5, company: "Massive Dynamic", contact: "William Bell", title: "CEO", industry: "BioTech", score: 95, status: "Qualified" },
];

export default function Leads() {
  return (
    <div className="flex flex-col gap-6 pb-12">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Leads & Prospects</h1>
        <p className="text-muted-foreground mt-2">
          Manage leads discovered by the Discovery Agent and scored by the Qualification Agent.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Discovered Leads</CardTitle>
          <CardDescription>
            Showing recent leads enriched and scored across BANT/MEDDIC parameters.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Company</TableHead>
                <TableHead>Contact</TableHead>
                <TableHead>Industry</TableHead>
                <TableHead>Opportunity Score</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {leads.map((lead) => (
                <TableRow key={lead.id}>
                  <TableCell className="font-medium">{lead.company}</TableCell>
                  <TableCell>
                    <div className="flex flex-col">
                      <span>{lead.contact}</span>
                      <span className="text-xs text-muted-foreground">{lead.title}</span>
                    </div>
                  </TableCell>
                  <TableCell>{lead.industry}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <div className="w-16 h-2 rounded-full bg-secondary overflow-hidden">
                        <div 
                          className={`h-full ${lead.score >= 80 ? 'bg-green-500' : lead.score >= 60 ? 'bg-yellow-500' : 'bg-red-500'}`}
                          style={{ width: `${lead.score}%` }}
                        />
                      </div>
                      <span className="text-sm font-medium">{lead.score}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline" className={
                      lead.status === 'Qualified' ? 'text-green-500 border-green-500/20 bg-green-500/10' :
                      lead.status === 'Warm' ? 'text-yellow-500 border-yellow-500/20 bg-yellow-500/10' :
                      'text-red-500 border-red-500/20 bg-red-500/10'
                    }>
                      {lead.status}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
