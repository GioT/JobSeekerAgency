import pandas as pd
import json
from datetime import datetime

def update_joblist(messages) -> None:
    """
    Tries to update the joblist list csv based on AWF results
    :param state messages:
    :return: None
    """

    todate     = datetime.today().strftime('%Y-%m-%d')
    jobs_json  = None
    df         = pd.read_csv('./output/updated_joblist.csv')
    df['date'] = pd.to_datetime(df['date'],format='%Y-%m-%d')
    
    try:
        jobs_json = json.loads(messages["messages"][-1].content)['jobs']
    except:
        print('>> could not find any relevant jobs or some issue with the query...')
    
    if jobs_json != None:
        df_tmp = pd.DataFrame(jobs_json).assign(date = todate, company=select.lower())
        df_tmp['date'] = pd.to_datetime(df_tmp['date'],format='%Y-%m-%d')
        
        if 11<3:
            df_tmp.to_csv('./output/updated_joblist.csv',sep=',',index=False)
        
        # make sure the columns name match before adding
        if all([x in list(df_tmp.columns) for x in ['name','url','date'] ]):
            df = pd.concat([df,df_tmp],axis=0).drop_duplicates().reset_index(drop=True)

        # keep oldest job if there is a duplicate:
        df = df.sort_values('date',ascending=True).groupby(['name','url','company']).first().reset_index()

        # update and save daily backup
        df.to_csv('./output/updated_joblist.csv',sep=',',index=False)
        df.to_csv(f'./output/bak/{todate}_joblist.csv',sep=',',index=False)
        print('done daily update!')
    
    return df

def df_to_gmail_html(df):
    """
    Convert a job listings DataFrame to a nicely formatted HTML table for Gmail.
    
    Args:
        df: DataFrame with columns 'name', 'url', 'company', 'date'
    
    Returns:
        str: HTML table string ready to paste into Gmail
    """
    html = """
<table style="border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; font-size: 14px;">
  <thead>
    <tr style="background-color: #4CAF50; color: white;">
      <th style="border: 1px solid #ddd; padding: 12px; text-align: left;">Job Title</th>
      <th style="border: 1px solid #ddd; padding: 12px; text-align: left;">Company</th>
      <th style="border: 1px solid #ddd; padding: 12px; text-align: left;">Date</th>
    </tr>
  </thead>
  <tbody>
"""
    for i, (_, row) in enumerate(df.iterrows()):
        bg_color = '#f2f2f2' if i % 2 == 0 else 'white'
        html += f"""    <tr style="background-color: {bg_color};">
      <td style="border: 1px solid #ddd; padding: 10px;"><a href="{row['url']}" style="color: #1a73e8; text-decoration: none;">{row['name']}</a></td>
      <td style="border: 1px solid #ddd; padding: 10px;">{row['company'].upper()}</td>
      <td style="border: 1px solid #ddd; padding: 10px;">{row['date']}</td>
    </tr>
"""
    html += """  </tbody>
</table>"""
    return html

def send_gmail_smtp(*, from_addr: str, to_addr: str, subject: str, body: str, html: bool = False):
    gmail_user = os.environ["GMAIL_USER"]              # e.g. "you@gmail.com"
    gmail_app_password = os.environ["GMAIL_APP_PASS"]  # 16-char App Password (no spaces)

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    
    if html:
        msg.set_content("Please view this email in an HTML-compatible client.")
        msg.add_alternative(body, subtype='html')
    else:
        msg.set_content(body)

    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.ehlo()
        s.starttls()
        s.login(gmail_user, gmail_app_password)
        s.send_message(msg)
    print("Email sent successfully!")