// Build: go build -o /tmp/ubt-go examples/go_strategy.go
// Config: {"strategy":{"type":"process","command":["/tmp/ubt-go"]}}
package main
import("bufio";"encoding/json";"fmt";"os")
type Bar struct{ Close float64 `json:"close"` }
type Input struct{ Bars []Bar `json:"bars"` }
func main(){
 s:=bufio.NewScanner(os.Stdin);s.Buffer(make([]byte,4096),8*1024*1024)
 for s.Scan(){var in Input
  if err:=json.Unmarshal(s.Bytes(),&in);err!=nil{fmt.Fprintln(os.Stderr,err);return}
  t:=0.0;n:=len(in.Bars)
  if n>=20{avg:=0.0;for _,b:=range in.Bars[n-20:]{avg+=b.Close};avg/=20
   if in.Bars[n-1].Close>avg {t=1}}
  fmt.Printf("{\"target\":%g}\n",t)
 }
}
