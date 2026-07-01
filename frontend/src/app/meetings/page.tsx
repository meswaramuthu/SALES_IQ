import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { CalendarDays, Clock, Video } from "lucide-react";

const meetings = [
  { id: 1, title: "Discovery Call: Acme Corp", time: "10:00 AM - 10:45 AM", date: "Today", attendee: "John Doe", status: "Upcoming", type: "Video" },
  { id: 2, title: "Product Demo: Globex", time: "1:00 PM - 2:00 PM", date: "Today", attendee: "Jane Smith", status: "Upcoming", type: "Video" },
  { id: 3, title: "Contract Negotiation: Initech", time: "3:30 PM - 4:00 PM", date: "Tomorrow", attendee: "Bill Lumbergh", status: "Upcoming", type: "Phone" },
  { id: 4, title: "Initial Chat: Soylent", time: "9:00 AM - 9:30 AM", date: "Yesterday", attendee: "Robert Paulson", status: "Completed", type: "Video" },
];

export default function Meetings() {
  return (
    <div className="flex flex-col gap-6 pb-12">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Meetings</h1>
        <p className="text-muted-foreground mt-2">
          View your upcoming and past meetings scheduled by the Booking Agent.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {meetings.map((meeting) => (
          <Card key={meeting.id}>
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between">
                <CardTitle className="text-lg leading-tight">{meeting.title}</CardTitle>
                <Badge variant={meeting.status === "Upcoming" ? "default" : "secondary"}>
                  {meeting.status}
                </Badge>
              </div>
              <CardDescription className="flex items-center gap-2 mt-2 text-primary/80">
                <CalendarDays className="w-4 h-4" />
                {meeting.date}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-3">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Clock className="w-4 h-4" />
                  {meeting.time}
                </div>
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <UsersIcon className="w-4 h-4" />
                  {meeting.attendee}
                </div>
                {meeting.status === "Upcoming" && (
                  <div className="mt-2 flex">
                    <button className="flex items-center gap-2 bg-primary/10 text-primary hover:bg-primary/20 px-3 py-1.5 rounded-md text-sm font-medium transition-colors">
                      <Video className="w-4 h-4" />
                      Join Meeting
                    </button>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function UsersIcon(props: any) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}
