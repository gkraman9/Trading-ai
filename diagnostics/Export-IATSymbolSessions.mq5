// Optional local source export. Read-only SymbolInfoSessionTrade calls only.
// Compile this reviewed repository file in MetaEditor; do not enable trading.
#property strict
#property script_show_inputs
input string SymbolName = "";       // Exact configured symbol; never printed.
input string BrokerTimeZone = "";   // Independently confirm the IANA zone.

bool SafeLabel(string value)
{
   if(StringLen(value)==0 || StringLen(value)>128) return false;
   for(int i=0; i<StringLen(value); i++)
   {
      ushort c=StringGetCharacter(value,i);
      if(c<33 || c>126 || c==34 || c==92) return false;
   }
   return true;
}
string WallTime(long seconds)
{
   return StringFormat("%02d:%02d",(int)(seconds/3600),(int)((seconds%3600)/60));
}
void OnStart()
{
   if(!TerminalInfoInteger(TERMINAL_CONNECTED) ||
      AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO ||
      TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))
   { Print("IAT: connected demo terminal with algorithmic trading disabled required."); return; }
   if(!SafeLabel(SymbolName) || !SafeLabel(BrokerTimeZone))
   { Print("IAT: explicit symbol and verified IANA timezone required."); return; }
   string days[7]={"mon","tue","wed","thu","fri","sat","sun"};
   int native_days[7]={1,2,3,4,5,6,0};
   string collected=TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS);
   StringReplace(collected,".","-");
   StringReplace(collected," ","T");
   collected+="Z";
   string body="{\"version\":1,\"kind\":\"WEEKLY\",\"symbol\":\""+SymbolName+
               "\",\"collected_at_utc\":\""+collected+"\",\"timezone\":\""+BrokerTimeZone+"\",\"weekdays\":{";
   for(int day=0; day<7; day++)
   {
      if(day>0) body+=",";
      body+="\""+days[day]+"\":[";
      for(uint index=0; index<=8; index++)
      {
         datetime from=0,to=0;
         ResetLastError();
         bool found=SymbolInfoSessionTrade(SymbolName,(ENUM_DAY_OF_WEEK)native_days[day],index,from,to);
         if(!found)
         {
            if(GetLastError()!=0) { Print("IAT: session metadata unavailable; no export produced."); return; }
            break;
         }
         if(index==8) { Print("IAT: excessive session count; no export produced."); return; }
         long a=((long)from)%86400, b=((long)to)%86400;
         if(a<0 || b<0 || a%60!=0 || b%60!=0 ||
            (a==b && (long)to-(long)from!=86400))
         { Print("IAT: ambiguous session boundary; no export produced."); return; }
         int offset=(b<=a ? 1 : 0);
         if(index>0) body+=",";
         body+="{\"open\":\""+WallTime(a)+"\",\"close\":\""+WallTime(b)+
               "\",\"close_day_offset\":"+IntegerToString(offset)+"}";
      }
      body+="]";
   }
   body+="}}";
   string filename="iat-sessions-"+IntegerToString((long)TimeLocal())+"-"+
                   IntegerToString((long)GetMicrosecondCount())+".json";
   if(FileIsExist(filename)) { Print("IAT: generated filename already exists; export refused."); return; }
   int handle=FileOpen(filename,FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   if(handle==INVALID_HANDLE) { Print("IAT: export could not be saved."); return; }
   bool written=FileWriteString(handle,body)==(uint)StringLen(body);
   FileFlush(handle);
   FileClose(handle);
   if(!written) { FileDelete(filename); Print("IAT: export incomplete."); return; }
   Print("IAT: weekly metadata saved in MQL5 Files: "+filename+"; dates and holidays remain unverified.");
}
