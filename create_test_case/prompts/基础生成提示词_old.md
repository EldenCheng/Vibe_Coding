---

# Prompt: Generate QA Test Cases

Based on the System State Machine and Flowchart logic described above, please generate a comprehensive suite of QA Test Cases for this product.

### Requirements:

1. **Test Case Design Principle**:
   
   - **English**: All test cases are writen by English.
   - **Atomic Test Cases**: Each test case should verify exactly ONE specific behavior
   - **One Verification Point**: Each test case has only 1 verification point to ensure clear pass/fail criteria
   - **Clear Separation**: Separate different verifications into different test cases

2. **Test Coverage**:
   
   - **Happy Path / Correct input / Functional Testing**: Successful end-to-end user journeys
   - **Incorrect input Testing**:
   - **Negative Input / Unexpect**: e.g, Wrong input against the logic defined. Press different buttons / Power cycle to try to interrupt the animation or audio playing, and so on. The Expected Result may need to guess the object to be tested how to handle this and add a [TBD] in the end to mark it is from guessing.
   - **Mode Switch**:
   - **Boundary & Counter Testing**: Validate loop limits and multi-touch combos (e.g., exactly 3 water counts to bloom, 7 interactions to ready, the tiered 2-short-touch combos on the head button).
   - **Timeouts & States**: Ensure all specific idle timeouts (4-5s, 8-10s, 20s, 30s) correctly trigger their respective idle/sleep animations or state changes.
   - **Interrupts & Exceptions**: Test the global 3-second dual-button hard reset/interrupt, and low battery branches.
   - **Duration and Stress Test**:

3. ***Output**:

4. Please present the test cases in a clean Json format, the file should including below:
   
   1. The test cases should including below sections:
      
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
