function doPost(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var data = JSON.parse(e.postData.contents);
  
  // Headers if sheet is empty
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(["Timestamp", "Category", "SubCategory", "Duration (min)", "Memo", "Source", "EventID"]);
  }
  
  // Append the data
  sheet.appendRow([
    data.Date,
    data.Category,
    data.SubCategory,
    data.Duration,
    data.Memo,
    data.Source,
    data.EventID || ""
  ]);
  
  return ContentService.createTextOutput("Success").setMimeType(ContentService.MimeType.TEXT);
}
