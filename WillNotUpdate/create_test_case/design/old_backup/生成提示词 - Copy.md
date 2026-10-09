---

# Prompt: Generate QA Test Cases

Based on the System State Machine and Flowchart logic described above, please generate a comprehensive suite of QA Test Cases for this product.

### Requirements:

1. **Test Case Design Principle**:
   
   - **Atomic Test Cases**: Each test case should verify exactly ONE specific behavior
   - **One Verification Point**: Each test case has only 1 verification point to ensure clear pass/fail criteria
   - **Clear Separation**: Separate different verifications into different test cases

2. **Test Coverage**:
   
   - **Happy Path / Functional Testing**: Successful end-to-end user journeys (e.g., Powering on -> Watering to bloom -> Caterpillar interactions -> Transformation -> Butterfly Mode).
   - **Negative Input**: e.g, Wrong input against the logic defined. Press different buttons / Power cycle to try to interrupt the animation or audio playing, and so on. The Expected Result may need to guess the object to be tested how to handle this and add a [TBD] in the end to mark it is from guessing.
   - **Boundary & Counter Testing**: Validate loop limits and multi-touch combos (e.g., exactly 3 water counts to bloom, 7 interactions to ready, the tiered 2-short-touch combos on the head button).
   - **Timeouts & States**: Ensure all specific idle timeouts (4-5s, 8-10s, 20s, 30s) correctly trigger their respective idle/sleep animations or state changes.
   - **Interrupts & Exceptions**: Test the global 3-second dual-button hard reset/interrupt, and low battery branches.

3. ***Output**:

4. Please present the test cases in a clean excel file, the file should including below sheets
   
   1. **Summary**
      
      The first sheet should be the Summary Sheet, in this sheet, create a table to summarize the status of the test cases of each mode(the data is count from the other sheets), each mode is a row, then the column including the total number, executed number, passed number, failed number, skipped number of the test cases of this mode, all the counting numbers from the corresponding data of the sheet of the mode.
      
      Use COUNTIF formulas to auto-count from mode sheets when tester fills the Results column.
   
   2. **Core Modes**
      
      Every Core Mode should has its own sheet. The project has 4 modes:
      
      - Bud Mode & Blooming Flow
      - Caterpillar Mode
      - Transformation Flow
      - Butterfly Mode
      
      Fill the test cases belongs to the corresponding mode. Group test cases by test area within each mode sheet:
      
      **Test Areas (Grouped by Color)**:
      
      - Happy Path / Functional (Green fill)
      - Negative Input (Red fill) - with [TBD] marking
      - Boundary & Counter (Yellow fill)
      - Timeouts & States (Blue fill)
      - Interrupts & Exceptions (Purple fill)
      
      The test cases should including below sections:
      
      | Test ID | Test Description | Expected Result | Results(Passed / Failed / Skipped) | Comment | Internal Bug ID | External Bug ID |
      | ------- | ---------------- | --------------- | ---------------------------------- | ------- | --------------- | --------------- |
      |         |                  |                 |                                    |         |                 |                 |
      
      Each section should be a column. And:
      
      1. **Test ID**: It starts from 1, and auto increase 1 by 1.
      
      2. **Test Description**: It should be from the logic of the flowchart, describing exactly ONE verification point.
      
      3. **Expected Result**: It should be from the logic of the flowchart. For negative test cases, add [TBD] at the end if the result is guessed.
      
      4. **Results(Passed / Failed / Skipped)**: It should be blank in the beginning and let the tester to fill. After the tester filled a result into this column, the data should be counted in the corresponding table cell of the Summary sheet using COUNTIF formulas.
      
      5. **Comment**: It should be blank in the beginning and let the tester to fill.
      
      6. **Internal Bug ID**: It should be blank in the beginning and let the tester to fill.
      
      7. **External Bug ID**: It should be blank in the beginning and let the tester to fill.
      
      And group the test cases from the same test area of a Mode, with color coding to distinguish different test areas.
